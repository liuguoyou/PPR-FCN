import tempfile
import subprocess
import shlex
import os
import numpy as np
import scipy.io
import cv2
script_dirname = os.path.abspath(os.path.dirname(__file__))

np.set_printoptions(threshold='nan')

def get_windows(image_fnames, cmd='edge_boxes_wrapper',alpha=0.6,beta=0.7,minscore=0.01,maxboxes=1e4):
    """
    Run MATLAB EdgeBoxes code on the given image filenames to
    generate window proposals.

    Parameters
    ----------
    image_filenames: strings
        Paths to images to run on.
    cmd: string
        edge boxes function to call:
            - 'edge_boxes_wrapper' for effective detection proposals paper configuration.
    """
    # Form the MATLAB script command that processes images and write to
    # temporary results file.
    f, output_filename = tempfile.mkstemp(suffix='.mat')
    os.close(f)
    fnames_cell = '{' + ','.join("'{}'".format(x) for x in image_fnames) + '}'
    command = "{}({}, '{}',{},{},{},{})".format(cmd, fnames_cell, output_filename,alpha,beta,minscore,maxboxes)

    # Execute command in MATLAB.
    mc = "matlab -nojvm -r \"{};exit\"".format(command)
    pid = subprocess.Popen(
        shlex.split(mc), cwd=script_dirname)
    retcode = pid.wait()
    if retcode != 0:
        raise Exception("Matlab script did not exit successfully!")

    # Read the results and undo Matlab's 1-based indexing.
    all_boxes = list(scipy.io.loadmat(output_filename)['all_boxes'][0])
    subtractor = np.array((1, 1, 0, 0, 0))[np.newaxis, :]
    all_boxes = [boxes - subtractor for boxes in all_boxes]

    # Remove temporary file, and return.
    os.remove(output_filename)
    if len(all_boxes) != len(image_fnames):
        raise Exception("Something went wrong computing the windows!")

    #print(all_boxes[0])
    return all_boxes

if __name__ == '__main__':
    """
    Run a demo.
    """
    import time

    image_filenames = [
        #'peppers.png',
        script_dirname + '/resized.jpg',
        #script_dirname + '/001551.jpg'
        #script_dirname + '/cat.jpg'
    ]
    # im = cv2.imread('indoor.jpg')
    # im = cv2.resize(im,(480,640))
    # cv2.imwrite('resized.jpg',im)

    t = time.time()
    boxes = get_windows(image_filenames)
    #print(boxes)
    print("EdgeBoxes processed {} images in {:.3f} s".format(
        len(image_filenames), time.time() - t))
