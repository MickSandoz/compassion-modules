# -*- encoding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2014 Compassion CH (http://www.compassion.ch)
#    Releasing children from poverty in Jesus' name
#    @author: Loic Hausammann <loic_hausammannn@hotmail.com>
#
#    The licence is in the file __openerp__.py
#
##############################################################################
"""
Define a few function that are useful in order to detect a pattern using the
sift implementation in opencv.
A method (keyPointCenter) has been defined in order to find an approximation
of the center based on the keypoint detected.
"""
import cv2
import numpy as np
import base64
import tempfile
from copy import deepcopy

from openerp import _
from openerp.exceptions import Warning


##########################################################################
#                           GENERAL METHODS                              #
##########################################################################
def patternRecognition(image, pattern, crop_area=None,
                       threshold=2, full_result=False):
    """
    Try to find a pattern in the subset (given by crop_area) of the image.

    :param image: Image to analyze array
    :param pattern: Pattern image data (array or str encoded in base64)
    :param list crop_area: Subset of the image to cut (relative position). \
                           [x_min, x_max, y_min, y_max]
    :param int threshold: Number of keypoints to find in order \
    to define a match
    :param bool full_result: if True, returns result from pattern too

    :returns: None if not enough keypoints found, position of the keypoints \
    (first index image/pattern)
    :rtype: np.array(), np.array()
    """
    if crop_area is None:
        crop_area = [0, 1, 0, 1]
    # read images
    img1 = deepcopy(image)
    if img1 is None:
        raise Warning(
            _("Could not read template image"),
            _("Template image is broken"))
    if isinstance(pattern, str):
        with tempfile.NamedTemporaryFile() as temp:
            temp.write(base64.b64decode(pattern))
            temp.flush()
            img2 = cv2.imread(temp.name,
                              cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
    else:
        img2 = pattern
    if img2 is None:
        raise Warning(
            _("Could not read pattern image"),
            _("The pattern image is broken"))

    # cut the part useful for the recognition
    (xmin, ymin), img1 = subsetImage(img1, crop_area)

    # compute the keypoints
    sift = cv2.xfeatures2d.SIFT_create()
    kp1, des1 = sift.detectAndCompute(img1, None)
    kp2, des2 = sift.detectAndCompute(img2, None)

    if des1 is None or des2 is None:
        return None

    # find matches between the two pictures
    good = findMatches(des1, des2)

    if full_result:
        return kp1, kp2, good
    if len(good) >= threshold:
        # put in a np.array the position of the image's keypoints
        keypoints = np.array([kp1[i[0].queryIdx].pt for i in good])
        # compute the position in the original picture
        keypoints = keypoints + np.array((xmin, ymin))
        return keypoints
    else:
        return None


def subsetImage(img, crop_area):
    """
    Cut a part of the image given by crop_area.
    Box is a tuple (of 2) containg a list of two elements.
    The tuple gives the choice between the width and the height,
    the list between the min and the max

    :param array img: Image read by cv2.imread
    :param list[] crop_area: Relative coordinate to cut
    :returns: Minimum in X and Y and the subset of the image
    :rtype: tuple(),array
    """
    h, w = img.shape[:2]
    # compute absolute coordinates
    xmin = round(w * crop_area[0])
    xmax = round(w * crop_area[1])
    ymin = round(h * crop_area[2])
    ymax = round(h * crop_area[3])
    # in opencv first index->height
    return (xmin, ymin), img[ymin:ymax, xmin:xmax]


def findMatches(des1, des2, test=0.8):
    """
    Look through the descriptor in order to find some matches.

    :param list[] des1: Descriptor of the image
    :param list[] des2: Descriptor of the template
    :returns: Matches found in the descriptors
    :rtype: list[Keypoints]
    """
    bf = cv2.BFMatcher()
    matches = bf.knnMatch(des1, des2, k=2)
    # Apply ratio test
    good = []
    for m, n in matches:
        if m.distance < test * n.distance:
            good.append([m])

    return good


def keyPointCenter(keypoints):
    """
    Compute the Center of the keypoints by using a weight computed
    with the distance (therefore a point far away from the main group
    [for example in case of error in the matching function] will have
    a small weight)

    :param np.array() keypoints: Keypoints computed by \
    :func:`patternRecognition` for either the image or the template
    :returns: Coordinates of the center
    :rtype: list[float]
    """
    # if not keypoints:
    if type(keypoints) is bool:
        return
    if len(keypoints) <= 1:
        return keypoints
    else:
        # normalization of the weights
        N = 0
        # return value
        center = np.array([0.0, 0.0])
        for i in keypoints:
            omega = 0
            for j in keypoints:
                # compute the distance
                omega += np.sum((np.array(i) - np.array(j)) ** 2)
            # invert the weight in order to have a small one
            # for a keypoint far away
            if omega == 0:
                omega = 1e-8
            omega = 1.0 / np.sqrt(omega)
            N += omega
            center += omega * np.array(i)
        return center / N


def find_template(img, templates, test=False, threshold=0.8):
    """
    Use pattern recognition to detect which template correponds to img.

    :param img: Opencv Image to analyze
    :param templates: Collection of all templates
    :param bool test: Enable the test mode (return an image as the last \
        parameter). If False, the image is None.
    :param threshold: Ratio of the templates' keypoints requested
    :returns: Detected template, center position of detected pattern,\
        image showing the detected keypoints for all the template
    :rtype: template, layout, None or np.array
    """
    # number of keypoint related between the picture and the pattern
    max_ratio_keypoints = 0.0
    key_img = False
    matching_template = None
    if test:
        test_img = []
    else:
        test_img = None

    for template in templates:
        # Crop the image to speedup detection and avoid false positives
        crop_area = template.get_pattern_area()

        if test:
            recognition = patternRecognition(
                img, template.pattern_image, crop_area, full_result=True)
            with tempfile.NamedTemporaryFile() as temp:
                temp.write(base64.b64decode(template.pattern_image))
                temp.flush()
                img2 = cv2.imread(temp.name)
            (xmin, ymin), img1 = subsetImage(img, crop_area)
            if recognition is not None:
                kp1, kp2, good = recognition
                img3 = cv2.drawMatchesKnn(img1, kp1, img2,
                                          kp2, good, None, flags=2)
            else:
                img3 = img1
            test_img.append(img3)

        # try to recognize the pattern
        tmp_key = patternRecognition(
            img, template.pattern_image, crop_area)
        # check if it is a better result than before
        if (tmp_key is not None and
                (threshold < float(len(tmp_key)) / float(
                    template.nber_keypoints) > max_ratio_keypoints)):
            # save all the data if it is better
            max_ratio_keypoints = float(
                len(tmp_key))/float(template.nber_keypoints)
            key_img = tmp_key
            matching_template = template
    return matching_template, keyPointCenter(key_img), test_img
