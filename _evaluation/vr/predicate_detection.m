%   This file is for Predicting predicate 

%   Distribution code Version 1.0 -- Copyright 2016, AI lab @ Stanford University.
%   
%   The Code is created based on the method described in the following paper 
%   [1] "Visual Relationship Detection with Language Priors", 
%   Cewu Lu*, Ranjay Krishna*, Michael Bernstein, Li Fei-Fei, European Conference on Computer Vision, 
%   (ECCV 2016), 2016(oral). (* = indicates equal contribution)
%  
%   The code and the algorithm are for non-comercial use only.

%% computing Predicate Det. accuracy
fprintf('\n');
fprintf('#######  Top recall results  ####### \n');
recall100R = top_recall_Relationship(100, rlp_confs_ours, rlp_labels_ours, sub_bboxes_ours, obj_bboxes_ours);
recall50R = top_recall_Relationship(50, rlp_confs_ours, rlp_labels_ours, sub_bboxes_ours, obj_bboxes_ours);
fprintf('Predicate Det. R@100: %0.2f \n', 100*recall100R);
fprintf('Predicate Det. R@50: %0.2f \n', 100*recall50R);

fprintf('\n');
fprintf('#######  Zero-shot results  ####### \n');
zeroShot100R = zeroShot_top_recall_Relationship(100, rlp_confs_ours, rlp_labels_ours, sub_bboxes_ours, obj_bboxes_ours);
zeroShot50R = zeroShot_top_recall_Relationship(50, rlp_confs_ours, rlp_labels_ours, sub_bboxes_ours, obj_bboxes_ours);
fprintf('zero-shot Predicate Det. R@100: %0.2f \n', 100*zeroShot100R);
fprintf('zero-shot Predicate Det. R@50: %0.2f \n', 100*zeroShot50R);


 