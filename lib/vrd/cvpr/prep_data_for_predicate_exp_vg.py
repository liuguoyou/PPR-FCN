import _init_paths
from vrd.test import test_net
from fast_rcnn.config import cfg, cfg_from_file, cfg_from_list
from datasets.factory import get_imdb
import caffe
import argparse
import pprint
import time, os, sys
import numpy as np
import h5py
import cv2

import scipy.io as sio

from fast_rcnn.config import cfg, get_output_dir
from fast_rcnn.bbox_transform import clip_boxes, bbox_transform_inv
import argparse
from utils.timer import Timer
import numpy as np
import cv2

import caffe
import h5py
from fast_rcnn.nms_wrapper import nms
import cPickle
from utils.blob import im_list_to_blob
import os

import utils.zl_utils as zl

def _get_image_blob(im):
    """Converts an image into a network input.

    Arguments:
        im (ndarray): a color image in BGR order

    Returns:
        blob (ndarray): a data blob holding an image pyramid
        im_scale_factors (list): list of image scales (relative to im) used
            in the image pyramid
    """
    im_orig = im.astype(np.float32, copy=True)
    im_orig -= cfg.PIXEL_MEANS

    im_shape = im_orig.shape
    im_size_min = np.min(im_shape[0:2])
    im_size_max = np.max(im_shape[0:2])

    processed_ims = []
    im_scale_factors = []

    for target_size in cfg.TEST.SCALES:
        im_scale = float(target_size) / float(im_size_min)
        # Prevent the biggest axis from being more than MAX_SIZE
        if np.round(im_scale * im_size_max) > cfg.TEST.MAX_SIZE:
            im_scale = float(cfg.TEST.MAX_SIZE) / float(im_size_max)
        im = cv2.resize(im_orig, None, None, fx=im_scale, fy=im_scale,
                        interpolation=cv2.INTER_LINEAR)
        im_scale_factors.append(im_scale)
        processed_ims.append(im)

    # Create a blob to hold the input images
    blob = im_list_to_blob(processed_ims)

    return blob, np.array(im_scale_factors)

def _get_rois_blob(im_rois, im_scale_factors):
    """Converts RoIs into network inputs.

    Arguments:
        im_rois (ndarray): R x 4 matrix of RoIs in original image coordinates
        im_scale_factors (list): scale factors as returned by _get_image_blob

    Returns:
        blob (ndarray): R x 5 matrix of RoIs in the image pyramid
    """
    rois, levels = _project_im_rois(im_rois, im_scale_factors)
    rois_blob = np.hstack((levels, rois))
    return rois_blob.astype(np.float32, copy=False)

def _project_im_rois(im_rois, scales):
    """Project image RoIs into the image pyramid built by _get_image_blob.

    Arguments:
        im_rois (ndarray): R x 4 matrix of RoIs in original image coordinates
        scales (list): scale factors as returned by _get_image_blob

    Returns:
        rois (ndarray): R x 4 matrix of projected RoI coordinates
        levels (list): image pyramid levels used by each projected RoI
    """
    im_rois = im_rois.astype(np.float, copy=False)

    if len(scales) > 1:
        widths = im_rois[:, 2] - im_rois[:, 0] + 1
        heights = im_rois[:, 3] - im_rois[:, 1] + 1

        areas = widths * heights
        scaled_areas = areas[:, np.newaxis] * (scales[np.newaxis, :] ** 2)
        diff_areas = np.abs(scaled_areas - 224 * 224)
        levels = diff_areas.argmin(axis=1)[:, np.newaxis]
    else:
        levels = np.zeros((im_rois.shape[0], 1), dtype=np.int)

    rois = im_rois * scales[levels]

    return rois, levels

def _get_blobs(im, rois):
    """Convert an image and RoIs within that image into network inputs."""
    blobs = {'data': None, 'rois': None}
    blobs['data'], im_scale_factors = _get_image_blob(im)
    if not cfg.TEST.HAS_RPN:
        blobs['rois'] = _get_rois_blob(rois, im_scale_factors)
    return blobs, im_scale_factors

def im_detect(net, im, boxes=None):
    """Detect object classes in an image given object proposals.

    Arguments:
        net (caffe.Net): Fast R-CNN network to use
        im (ndarray): color image to test (in BGR order)
        boxes (ndarray): R x 4 array of object proposals or None (for RPN)

    Returns:
        scores (ndarray): R x K array of object class scores (K includes
            background as object category 0)
        boxes (ndarray): R x (4*K) array of predicted bounding boxes
    """
    blobs, im_scales = _get_blobs(im, boxes)
    # When mapping from image ROIs to feature map ROIs, there's some aliasing
    # (some distinct image ROIs get mapped to the same feature ROI).
    # Here, we identify duplicate feature ROIs, so we only compute features
    # on the unique subset.
    # if cfg.DEDUP_BOXES > 0 and not cfg.TEST.HAS_RPN:
        # v = np.array([1, 1e3, 1e6, 1e9, 1e12])
        # hashes = np.round(blobs['rois'] * cfg.DEDUP_BOXES).dot(v)
        # _, index, inv_index = np.unique(hashes, return_index=True,
                                        # return_inverse=True)
        # blobs['rois'] = blobs['rois'][index, :]
        # boxes = boxes[index, :]

    if cfg.TEST.HAS_RPN:
        im_blob = blobs['data']
        blobs['im_info'] = np.array(
            [[im_blob.shape[2], im_blob.shape[3], im_scales[0]]],
            dtype=np.float32)

    # reshape network inputs
    net.blobs['data'].reshape(*(blobs['data'].shape))
    if cfg.TEST.HAS_RPN:
        net.blobs['im_info'].reshape(*(blobs['im_info'].shape))
    else:
        net.blobs['rois'].reshape(*(blobs['rois'].shape))

    # do forward
    forward_kwargs = {'data': blobs['data'].astype(np.float32, copy=False)}
    if cfg.TEST.HAS_RPN:
        forward_kwargs['im_info'] = blobs['im_info'].astype(np.float32, copy=False)
    else:
        forward_kwargs['rois'] = blobs['rois'].astype(np.float32, copy=False)
    blobs_out = net.forward(**forward_kwargs)

    if cfg.TEST.HAS_RPN:
        assert len(im_scales) == 1, "Only single-image batch implemented"
        rois = net.blobs['rois'].data.copy()
        # unscale back to raw image space
        boxes = rois[:, 1:5] / im_scales[0]

    if cfg.TEST.SVM:
        # use the raw scores before softmax under the assumption they
        # were trained as linear SVMs
        scores = net.blobs['cls_score'].data
    else:
        # use softmax estimated probabilities
        scores = blobs_out['cls_prob']

    # if cfg.TEST.BBOX_REG:
    if False:
        # Apply bounding-box regression deltas
        box_deltas = blobs_out['bbox_pred']
        pred_boxes = bbox_transform_inv(boxes, box_deltas)
        pred_boxes = clip_boxes(pred_boxes, im.shape)
    else:
        # Simply repeat the boxes, once for each class
        pred_boxes = np.tile(boxes, (1, scores.shape[1]))

    # if cfg.DEDUP_BOXES > 0 and not cfg.TEST.HAS_RPN:
        # # Map scores and predictions back to the original set of boxes
        # scores = scores[inv_index, :]
        # pred_boxes = pred_boxes[inv_index, :]
    fc7 = net.blobs['fc7'].data
    return net.blobs['cls_score'].data[:, :], scores, fc7, pred_boxes


def prep_pre(split_type):
    if split_type!='train' and split_type!='test':
        print 'error'
        exit(0)
    caffe.set_mode_gpu()
    caffe.set_device(0)

    m = h5py.File('/home/zawlin/Dropbox/proj/vg1_2_meta.h5', 'r', 'core')

    cfg.TEST.HAS_RPN=False
    net = caffe.Net('models/vg1_2/vgg16/faster_rcnn_end2end/test_jointbox.prototxt',
                    'output/models/vg1_2_vgg16_faster_rcnn_finetune_iter_145000.caffemodel',caffe.TEST)
    # net.name = os.path.splitext(os.path.basename(args.caffemodel))[0]
    h5path = 'output/precalc/vg1_2_2016_predicate_exp_%s.hdf5'%split_type

    h5f = h5py.File(h5path)
    cnt =0
    for k in h5f.keys():
        if cnt %1000==0:
            print cnt
        cnt += 1
        if 'sub_visual' not in h5f[k]:
            print k
    print len(h5f.keys())
    exit(0)
    root = 'data/vg1_2_2016/Data/%s/'%split_type
    _t = {'im_detect': Timer(), 'misc': Timer()}
    cnt = 0
    thresh = .01
    for imid in m['gt/%s'%split_type].keys():
        cnt += 1
        impath = zl.imid2path(m,imid)
        fpath = os.path.join(root, impath)
        im = cv2.imread(fpath)
        if im == None:
            print fpath
        if cnt %100==0:
            print cnt
        fpath = os.path.join(root, impath)
        im = cv2.imread(fpath)
        if im == None:
            print fpath
        gt_sub_boxes = m['gt/%s/%s/sub_boxes'%(split_type,imid)][...]
        gt_obj_boxes= m['gt/%s/%s/obj_boxes'%(split_type,imid)][...]
        gt_rlp_labels= m['gt/%s/%s/rlp_labels'%(split_type,imid)][...]

        sub_boxes = []
        obj_boxes = []
        joint_boxes = []
        boxes_batch = []
        b_type = {}
        b_idx = 0
        sub_visual = []
        obj_visual = []
        joint_visual = []
        pre_label = []
        sub_cls = []
        obj_cls = []
        for i in xrange(gt_sub_boxes.shape[0]):
            gt_sub_box = gt_sub_boxes[i][...]
            gt_obj_box = gt_obj_boxes[i][...]
            gt_rlp_label= gt_rlp_labels[i][...]

            pre_idx = gt_rlp_label[1]
            sub_cls_idx = gt_rlp_label[0]
            obj_cls_idx = gt_rlp_label[2]

            sub_cls.append(sub_cls_idx)
            obj_cls.append(obj_cls_idx)
            pre_label.append(pre_idx)

            #print sub_lbl,predicate,obj_lbl
            joint_bbox = [min(gt_sub_box[0],gt_obj_box[0]), min(gt_sub_box[1],gt_obj_box[1]),max(gt_sub_box[2],gt_obj_box[2]),max(gt_sub_box[3],gt_obj_box[3])]

            joint_boxes.append(joint_bbox)
            sub_boxes.append(gt_sub_box)
            obj_boxes.append(gt_obj_box)
            # cv2.rectangle(im,(joint_bbox[0],joint_bbox[1]),(joint_bbox[2],joint_bbox[3]),(255,255,255),4)
            # cv2.rectangle(im,(sub_bbox[0],sub_bbox[1]),(sub_bbox[2],sub_bbox[3]),(0,0,255),2)
            # cv2.rectangle(im,(obj_bbox[0],obj_bbox[1]),(obj_bbox[2],obj_bbox[3]),(255,0,0),2)


        for i in xrange(len(sub_boxes)):
            boxes_batch.append(sub_boxes[i])
            b_type[b_idx]='s'
            b_idx += 1
        for i in xrange(len(obj_boxes)):
            boxes_batch.append(obj_boxes[i])
            b_type[b_idx]='o'
            b_idx += 1
        for i in xrange(len(joint_boxes)):
            boxes_batch.append(joint_boxes[i])
            b_type[b_idx]='j'
            b_idx += 1
        box_proposals = None
        _t['im_detect'].tic()
        score_raw, scores, fc7, boxes = im_detect(net, im, np.array(boxes_batch))

        for i in xrange(scores.shape[0]):
            s_idx = np.argmax(scores[i,1:])+1
            cls_box=None
            cls_box = boxes[i, s_idx * 4:(s_idx + 1) * 4]
            if b_type[i] == 's':
                sub_visual.append(fc7[i])
            if b_type[i] == 'o':
                obj_visual.append(fc7[i])
            if b_type[i] == 'j':
                joint_visual.append(fc7[i])
            # cls_name = str(m['meta/cls/idx2name/' + str(s_idx)][...])
            # if b_type[i] == 's':
                # print str(m['meta/pre/idx2name/'+str(pre_label[i])][...])
            # cv2.rectangle(im,(cls_box[0],cls_box[1]),(cls_box[2],cls_box[3]),(255,0,0),2)
        # cv2.imshow('im',im)
        _t['im_detect'].toc()

        _t['misc'].tic()
        sub_visual= np.array(sub_visual).astype(np.float16)
        obj_visual= np.array(obj_visual).astype(np.float16)
        joint_visual= np.array(joint_visual).astype(np.float16)
        pre_label = np.array(pre_label).astype(np.int32)
        sub_boxes = np.array(sub_boxes).astype(np.int32)
        obj_boxes = np.array(obj_boxes).astype(np.int32)
        sub_cls = np.array(sub_cls).astype(np.int32)
        obj_cls= np.array(obj_cls).astype(np.int32)

        h5f.create_dataset(imid + '/sub_visual', dtype='float16', data=sub_visual)
        h5f.create_dataset(imid + '/obj_visual', dtype='float16', data=obj_visual)
        h5f.create_dataset(imid + '/joint_visual', dtype='float16', data=joint_visual)
        h5f.create_dataset(imid + '/pre_label', dtype='float16', data=pre_label)
        h5f.create_dataset(imid + '/sub_boxes', dtype='float16', data=sub_boxes)
        h5f.create_dataset(imid + '/obj_boxes', dtype='float16', data=obj_boxes)
        h5f.create_dataset(imid + '/sub_cls', dtype='float16', data=sub_cls)
        h5f.create_dataset(imid + '/obj_cls', dtype='float16', data=obj_cls)
        _t['misc'].toc()
        # rpn_rois = net.blobs['rois'].data
        # pool5 = net.blobs['pool5'].data
        # _t['misc'].tic()
        # cnt += 1
        print 'im_detect: {:d} {:.3f}s {:.3f}s' \
            .format(cnt, _t['im_detect'].average_time,
                    _t['misc'].average_time)

prep_pre('train')
