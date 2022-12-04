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

from geometry_msgs.msg import Twist

# license plate working values
uh = 179
us = 10
uv = 210
lh = 0
ls = 0
lv = 90
lower_hsv = np.array([lh, ls, lv])
upper_hsv = np.array([uh, us, uv])

CAR_WIDTH = 200
CAR_HEIGHT = 320
PLATE_F = 270
PLATE_I = 220
PLATE_RES = (150, 298)

ID_TOP = 130
ID_BOT = 185
ID_LEFT = 110
ID_RIGHT = 190

font = cv2.FONT_HERSHEY_COMPLEX
font_size = 0.5


class PlatePull:

    def __init__(self):
        self.bridge = CvBridge()
        self.image_sub = rospy.Subscriber(
            "/R1/pi_camera/image_raw", Image, self.callback)
        self.twist_sub = rospy.Subscriber("/R1/cmd_vel", Twist, self.callback_twist)
        self.twist = (0,0,0) # lin x, ang z, lin z
        self.can_scrape = False

        self.i = 0

    def process_stream(self, image):
        """processes the image using a grey filter to catch license plates
        returns a cv image"""

        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower_hsv, upper_hsv)
        blur = cv2.GaussianBlur(mask, (5, 5), 0)
        dil = cv2.dilate(blur, (5, 5))

        return dil
    

    def get_moments(self, img):
        """Returns c, cx, cy. (Usually cx, cy are only important for debugging text)
        c is the largest contour; 
        cx, cy is the center of mass of the largest contour"""
        contours, hierarchy = cv2.findContours(
            image=img, mode=cv2.RETR_TREE, method=cv2.CHAIN_APPROX_NONE)

        # gets the biggest contour and its info
        c = max(contours, key=cv2.contourArea)
        M = cv2.moments(c)
        cx = int(M['m10']/M['m00'])
        cy = int(M['m01']/M['m00'])

        return  c, cx, cy

    def callback_twist(self, data):
        """Callback for the subscriber node of the /cmd_vel topic, called whenever there is a new message from this topic
        (i.e. new Twist values).

        Args:
            data (sensor_msgs::Twist): Twist object containing the robot's current velocities
        """        
        self.twist = (data.linear.x, data.angular.z, data.linear.z)
        # print(self.twist[0], self.twist[1])

    def callback(self, data):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(data, "bgr8")
        except CvBridgeError as e:
            print(e)

        out = cv_image.copy()
        processed_im = self.process_stream(cv_image)

        # draw contours on the original image

        c, cx, cy = self.get_moments(processed_im)

        # draws a circle at the center of mass of contour
        # disp = cv2.circle(out, (cx, cy), 2, (0, 255, 0), 2)

        # approximates the contour to a simpler shape
        epsilon = 0.1  # higher means simplify more
        perimiter = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, epsilon*perimiter, True)

        n = approx.ravel()
        pts = np.float32(self.get_coords(n)).reshape(-1, 2)
        sorted_pts = self.contour_coords_sorted(pts)

        # cv2.putText(disp, "tl", (int(sorted_pts[0][0]), int(
        #     sorted_pts[0][1])), font, font_size, (0, 255, 0))
        # cv2.putText(disp, "tr", (int(sorted_pts[1][0]), int(
        #     sorted_pts[1][1])), font, font_size, (0, 255, 0))
        # cv2.putText(disp, "bl", (int(sorted_pts[2][0]), int(
        #     sorted_pts[2][1])), font, font_size, (0, 255, 0))
        # cv2.putText(disp, "br", (int(sorted_pts[3][0]), int(
        #     sorted_pts[3][1])), font, font_size, (0, 255, 0))
        # print(pts)

        # resizing to have pairs of points
        plate_view = self.transform_perspective(
            CAR_WIDTH, CAR_HEIGHT, sorted_pts, out)

        # cv2.drawContours(image=disp, contours=[
        #                  approx], contourIdx=-1, color=(0, 255, 0), thickness=2, lineType=cv2.LINE_AA)

        cv2.imshow('plate_view', plate_view)

        char_imgs = []
        for i in range(4):
          char_imgs.append(self.process_plate(i, plate_view))

        plate_id = self.plate_id_img(plate_im=plate_view)

        alpha_edge_PATH = '/home/fizzer/ros_ws/src/ENPH353-Team12/src/alpha-edge-data/plate_'
        num_edge_PATH = '/home/fizzer/ros_ws/src/ENPH353-Team12/src/num-edge-data/plate_'
        id_PATH = '/home/fizzer/ros_ws/src/ENPH353-Team12/src/id-data/carID_'

        # cv2.imshow('char 1', char_imgs[0])
        # cv2.imshow('char 2', char_imgs[1])
        # cv2.imshow('char 3', char_imgs[2])
        # cv2.imshow('char 4', char_imgs[3])
        
        cv2.imshow('plate_view', plate_view)
        # cv2.imshow('plate_id', plate_id)
        cv2.waitKey(3)

        if not self.can_scrape and self.twist[2] > 0:
            self.can_scrape = True
            print('started scrape')
        if self.can_scrape and self.twist[2] < 0:
            self.can_scrape = False
            print('stopped scrape')
        if not self.can_scrape:
            return

        r = random.random()
        r2 = random.random()
        cv2.imwrite(alpha_edge_PATH + 'Z' + str(r) + '.png', cv2.cvtColor(char_imgs[0], cv2.COLOR_BGR2GRAY))
        cv2.imwrite(alpha_edge_PATH + 'Z' + str(r2) + '.png', cv2.cvtColor(char_imgs[1], cv2.COLOR_BGR2GRAY))        
        # cv2.imwrite(num_edge_PATH + '9' + str(r) + '.png', cv2.cvtColor(char_imgs[2], cv2.COLOR_BGR2GRAY))
        # cv2.imwrite(num_edge_PATH + '9' + str(r2) + '.png', cv2.cvtColor(char_imgs[3], cv2.COLOR_BGR2GRAY))

        # cv2.imwrite(id_PATH + '3' + str(r) + '.png', cv2.cvtColor(plate_id, cv2.COLOR_BGR2GRAY))


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

    def process_plate(self, pos, plate_im):
        """Crops and processes plate images for individual letter.
        Args: pos - the position in the license plate
              plate_im - image of license plate
        Returns: processed image the character"""

        crop = plate_im[PLATE_I:PLATE_F, int(
            pos*CAR_WIDTH/4):int((pos + 1)*CAR_WIDTH/4)]
        resize = cv2.resize(crop, PLATE_RES)

        return resize

    def transform_perspective(self, width, height, sorted_pts, image):
        """Args: The coords of the polygon we are to transform into a rectangle.
                 Desired width and height of the transformed image.
                 The image from which we pull the polygon.
                 Returns: The polygon from the original image transformed into a square."""
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

            i = i + 1

        return coords

    def contour_coords_sorted(self, list_of_points):
        """Args: List of contour verticies
           Returns: Verticies in list sorted by top to bottom, left to right"""

        avg_y = 0
        avg_x = 0

        for i in list_of_points:
            avg_y += i[1]
            avg_x += i[0]

        avg_y = int(avg_y/4)
        avg_x = int(avg_x/4)

        for i in list_of_points:
            if (int(i[1]) < avg_y and int(i[0]) < avg_x):
                tl = i
            elif (int(i[1]) < avg_y):
                tr = i
            elif (int(i[0]) < avg_x):
                bl = i
            else:
                br = i

        coords = [list(tl), list(tr), list(bl), list(br)]

        return np.float32(coords).reshape(-1, 2)


def main(args):
    pp = PlatePull()

    rospy.init_node('image_converter', anonymous=True)
    try:
        rospy.spin()
    except KeyboardInterrupt:
        print("Shutting down")
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main(sys.argv)