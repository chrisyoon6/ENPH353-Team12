#! /usr/bin/env python3

from __future__ import print_function
from concurrent.futures import process

#import roslib; roslib.load_manifest('node')
import sys
import rospy
import cv2
import random
import numpy as np
from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError
from char_reader import CharReader
from hsv_view import ImageProcessor

# license plate working values

CAR_WIDTH = 200
CAR_HEIGHT = 320
PLATE_F = 270
PLATE_I = 220
PLATE_RES = (150, 298)
ID_TOP = 130
ID_BOT = 185
ID_LEFT = 110
ID_RIGHT = 190


# PATH_NUM_MODEL = '/home/fizzer/ros_ws/src/ENPH353-Team12/src/models/num_model-1.1.1.h5'
# PATH_ALPHA_MODEL = '/home/fizzer/ros_ws/src/ENPH353-Team12/src/models/alpha_model-1.1.h5'
PATH_NUM_MODEL = '/home/fizzer/ros_ws/src/ENPH353-Team12/src/models/num_model2.h5'
PATH_ALPHA_MODEL = '/home/fizzer/ros_ws/src/ENPH353-Team12/src/models/alpha_model2.1.h5'
PATH_PARKING_ID = '/home/fizzer/ros_ws/src/ENPH353-Team12/src/models/id_model2.h5'

font = cv2.FONT_HERSHEY_COMPLEX
font_size = 0.5

AREA_LOWER_THRES = 10000
AREA_UPPER_THRES = 1000000

ROWS = 720
COLS = 1280

class PlateReader:
    """This class handles license plate recognition.
    """

    def __init__(self, script_run=True):
        self.bridge = CvBridge()
        if script_run:
            self.image_sub = rospy.Subscriber("/R1/pi_camera/image_raw", Image, self.callback)
        self.num_reader = CharReader(PATH_NUM_MODEL)
        self.alpha_reader = CharReader(PATH_ALPHA_MODEL)
        self.id_reader = CharReader(PATH_PARKING_ID)
        self.i = 0

    def get_moments(self, img, debug=False):
        """Returns the moment (contour) of an image: c, cx, cy. 

        Usually cx, cy are only important for debugging
        c is the largest contour; 
        cx, cy is the center of mass of the largest contour

        Args:
            image (cv::Mat): image that is thresholded to be processed 
            debug (bool): if true, returns cx, cy as well
        Returns:
            list[float]: a list of the largest contours
        """
        
        contours, hierarchy = cv2.findContours(
            image=img, mode=cv2.RETR_TREE, method=cv2.CHAIN_APPROX_NONE)

        # gets the biggest contour and its info
        if not contours:
            return []
        c = max(contours, key=cv2.contourArea)
        M = cv2.moments(c)
        cx = int(M['m10']/M['m00'])
        cy = int(M['m01']/M['m00'])

        if debug:
            return c, cx, cy

        return c

    def callback(self, data):
        """Handler of every callback when a new frame comes in

        Args:
            data (Image): For every new image, process that checks and reads plate
        """        
        try:
            cv_image = self.bridge.imgmsg_to_cv2(data, "bgr8")
        except CvBridgeError as e:
            print(e)

        p_v = self.get_plate_view(cv_image)

        if list(p_v):
            kernel = np.array([[-1,-1,-1], [-1,9.5,-1], [-1,-1,-1]])
            sharper = cv2.filter2D(p_v, -1, kernel)
            cv2.imshow("Plate view", p_v)
            cv2.imshow("Plate view sharper", sharper)
            cv2.waitKey(1)
        lp, p_vs = self.prediction_data_license(cv_image)
        if lp:
            print(lp)
            for p in p_vs:
                print(p)
            print("")

    def prediction_data_license(self, img):
        """Obtains the cnn's prediction data of a license plate.

        Args:
            img (cv::Mat): Raw image data containing a license plate to predict on

        Returns:
            tuple[str, ndarray]: string of characters representing the predicted license plate, and a 2D array of length 4, each element being an array containing the predicted probablities 
            of the corresponding character. Returns an empty string and an empty list if the image is invalid.
        """        
        p_v = self.get_plate_view(img)
        if list(p_v):
            c_img = self.get_char_imgs(p_v)
            pred, pred_vecs = self.characters(c_img, get_pred_vec=True)
            return pred, pred_vecs
        else:
            return "", []

    def prediction_data_id(self, img):
        """Obtains the cnn's prediction data of a plate ID.

        Args:
            img (cv::Mat): Raw image data containing a license plate to predict on

        Returns:
            tuple[str, array]: Number of the license plate ID and a 1D array containing the predicted probablities 
            of the corresponding character. Returns an empty string and an empty list if the image is invalid.
        """        
        p_v = self.get_plate_view(img)
        if list(p_v):
            id_img = self.plate_id_img(p_v)
            pred_vec = self.id_reader.predict_char(id_img, id=True)
            chr_out = self.id_reader.interpret(pred_vec)
            return chr_out, pred_vec
        else:
            return "", []

    def get_plate_view(self, img):
        """Obtains the projected rectangular view of a license plate contained within the input image.

        Args:
            img (cv::Mat): Raw image data containing the license plate.

        Returns:
            cv::Mat: Projected view of the license plate, or empty list if invalid image.
        """        
        processed_im = ImageProcessor.filter_plate(img, ImageProcessor.plate_low, ImageProcessor.plate_up)
        c = self.get_moments(processed_im)
        if not list(c):
            # no contour
            return []
        area = cv2.contourArea(c)
        if area < AREA_LOWER_THRES or area > AREA_UPPER_THRES:
            return []
        approx = self.approximate_plate(c, epsilon=0.1)
        verticies = self.verticies(approx_c=approx)
        
        if not list(verticies):
            # no verticies (i.e. no perspec. transform)
            return []
        plate_view = self.transform_perspective(CAR_WIDTH, CAR_HEIGHT, verticies, img)
        return plate_view

    def characters(self, char_imgs, get_pred_vec=False):
        """Gets the neural network predicted characters from the images of each character.

        Args:
            char_imgs (array[Image]): Array (length 4) of character images from the license plate.
                First two images should be of letters, second two should be of numbers.
            get_pred_vec (bool, optional): True if prediction data should also be returned. Defaults to False.
        Returns:
            str or tuple[str,ndarray]: a string representing the license plate. Also returns the prediction probabilities for each character if set to true. 
        """
        
        pred_vecs = []
        license_plate = ''
        for index,img in enumerate(char_imgs):
            if index < 2:
                prediction_vec = self.alpha_reader.predict_char(img=img)
                license_plate += CharReader.interpret(predict_vec=prediction_vec)
            else:
                prediction_vec = self.num_reader.predict_char(img=img)
                license_plate += CharReader.interpret(predict_vec=prediction_vec)
            pred_vecs.append(np.round(np.array(prediction_vec), 3))

        if get_pred_vec:
            return license_plate, np.array(pred_vecs)
        else:
            return license_plate

    def get_char_imgs(self, plate):
        """Gets the verticies of a simple shape such as a square, rectangle, etc.

        Args:
            plate (Image): rectangular image of the license plate
            id (bool, optional): True if the character is from the plate ID, not the license. Defaulted to False.
        Returns:
            list[cv::Mat]: list of images,
        """
        imgs = []
        for i in range(4):
            imgs.append(self.process_plate(i, plate))
        return imgs

    def verticies(self, approx_c):
        """Gets the verticies of a simple contour such as a square, rectangle, etc.

        Args:
            approx_c (***): approximated contour of which the verticies are found
        Returns:
            ndarray: verticies of the contour, from top to bottom, left to right. Empty list returned if invalid verticies.
        """
        n = approx_c.ravel()
        pts = np.float32(self.get_coords(n)).reshape(-1, 2)
        sorted_pts = PlateReader.contour_coords_sorted(pts)
        if not list(sorted_pts):
            return []

        sorted_pts_np = np.array(sorted_pts)
        if 0 in sorted_pts_np[:,0] or COLS-1 in sorted_pts_np[:,0]:
            return []
        if 0 in sorted_pts_np[:,1] or ROWS-1 in sorted_pts_np[:,1]:
            return []
        return sorted_pts

    def approximate_plate(self, contour, epsilon):
        """Approximates a contour to a simple shape such as a square, rectangle, etc.

        Args:
            contour (***): contour to be approximated
            epsilon (float in (0,1)): approximation accuracy
        """
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon*perimeter, True)
        return approx

    def process_plate(self, pos, plate_im):
        """Crops and processes plate images for individual letter.

        Args: pos - the position in the license plate
              plate_im - image of license plate

        Returns: processed image of plate
        """

        crop = plate_im[PLATE_I:PLATE_F, int(pos*CAR_WIDTH/4):int((pos + 1)*CAR_WIDTH/4)]
        resize = cv2.resize(crop, PLATE_RES)

        return resize

    def plate_id_img(self, plate_im):
        """Crops and processes plate images for parking ID.
        Args:
            plate_im (Image): image of the license plate
        Returns:
            Image: processed image of the parking ID
        """        
        crop = plate_im[ID_TOP:ID_BOT, ID_LEFT:ID_RIGHT]
        resize = cv2.resize(crop, PLATE_RES)
        return resize

    def transform_perspective(self, width, height, sorted_pts, image):
        """
        Args: 
            The coords of the polygon we are to transform into a rectangle.
            Desired width and height of the transformed image.
            The image from which we pull the polygon.
        Returns: 
            The polygon from the original image transformed into a square
        """
        pts = np.float32([[0, 0], [width, 0],
                          [0, height], [width, height]])
        Mat = cv2.getPerspectiveTransform(sorted_pts, pts)
        return cv2.warpPerspective(image, Mat, (width, height))

    def get_coords(self, contour):
        """Args: Approximated contour extracted with CHAIN_APPROX_NONE (only the verticies)
           Returns: List of verticies in (x,y) coords"""
        i = 0
        coords = []
        for j in contour:
            if (i % 2 == 0):
                x = contour[i]
                y = contour[i + 1]
                coords.append((x, y))
            i += 1
            
        return coords

    @staticmethod
    def contour_coords_sorted(list_of_points):
        """Sorts the verticies of a contour so it can be perspective transformed
        
        Args: 
            list[float]: List of contour verticies. Should have exactly 4 verticies with (x,y)
        
        Returns: 
            ndarray: Verticies in list sorted by top to bottom, left to right, with each verticies being an array with [col, row]
        """
        avg_y = 0
        avg_x = 0
        for i in list_of_points:
            avg_y += i[1]
            avg_x += i[0]

        avg_y = int(avg_y/4)
        avg_x = int(avg_x/4)

        tl = tr = bl = br = None

        for i in list_of_points:
            if (int(i[1]) < avg_y and int(i[0]) < avg_x):
                tl = i
            elif (int(i[1]) < avg_y):
                tr = i
            elif (int(i[0]) < avg_x):
                bl = i
            else:
                br = i
                
        if tl is None or tr is None or bl is None or br is None:
            return []

        tl = list(tl)
        tr = list(tr)
        bl = list(bl)
        br = list(br)

        coords = [tl, tr, bl, br]
        return np.float32(coords).reshape(-1, 2)

def main(args):
    pr = PlateReader(script_run=True)
    rospy.init_node('image_converter', anonymous=True)
    try:
        rospy.spin()
    except KeyboardInterrupt:
        print("Shutting down")
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main(sys.argv)
