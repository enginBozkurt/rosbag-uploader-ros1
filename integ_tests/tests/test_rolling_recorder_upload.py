#!/usr/bin/env python
# Copyright (c) 2020, Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
#  http://aws.amazon.com/apache2.0
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.

import math
import os
import random
import string
import sys
import tempfile
import time

import actionlib
import rosbag
import rosnode
import rospy
import rostest
import rostopic
from s3_client import S3Client

from recorder_msgs.msg import RollingRecorderAction, RollingRecorderGoal
from rolling_recorder_test_base import RollingRecorderTestBase
from std_msgs.msg import String

PKG = 'rosbag_uploader_ros1_integration_tests'
NAME = 'rolling_recorder_custom_topic'
ACTION = '/rolling_recorder/RosbagRollingRecord'
RESULT_SUCCESS = 0
GOAL_COMPLETION_TIMEOUT_SEC = 90.0

class TestRollingRecorderUploadOnGoal(RollingRecorderTestBase):
    def setUp(self):
        super(TestRollingRecorderUploadOnGoal, self).setUp()
        self.s3_region = rospy.get_param('/s3_file_uploader/aws_client_configuration/region')
        self.s3_bucket_name = rospy.get_param('/s3_file_uploader/s3_bucket')
        self.s3_client = S3Client(self.s3_region)
        self.s3_client.create_bucket(self.s3_bucket_name)
        self.s3_client.wait_for_bucket_create(self.s3_bucket_name)
        # Wait for rolling recorder node and action server to start
        self.wait_for_rolling_recorder_nodes()
        # Create publishers 
        self.topic_to_record = rospy.get_param("~topic_to_record")
        self.test_publisher = rospy.Publisher(self.topic_to_record, String, queue_size=10)
        self.wait_for_rolling_recorder_node_to_subscribe_to_topic()

    def tearDown(self):
       # print("=======================")
        super(TestRollingRecorderUploadOnGoal, self).setUp()
        self.s3_client.delete_all_objects(self.s3_bucket_name)
        self.s3_client.delete_bucket(self.s3_bucket_name)

    def test_record_upload(self):
        self.total_test_messages = 10

        start_time, s3_destination = self.run_rolling_recorder()
        self.send_rolling_recorder_upload_goal(s3_destination, start_time)

    def test_record_upload_multiple_times(self):
        self.total_test_messages = 10
        total_record_upload_attempts = 10

        for _ in range(total_record_upload_attempts):
            start_time, s3_destination = self.run_rolling_recorder()
            print("=======================")
            print(start_time)
            print(s3_destination)
            print("=======================")
            self.send_rolling_recorder_upload_goal(s3_destination, start_time)

    def run_rolling_recorder(self):
        # Find start time of active file
        active_rosbag = self.get_latest_bag_by_regex("*.bag.active")
        rospy.loginfo("Active rosbag: %s" % active_rosbag)
        active_rosbag_start_time = os.path.getctime(active_rosbag)
        start_time = rospy.Time.from_sec(math.floor(active_rosbag_start_time))

        # Calculate time active bag will roll over
        bag_finish_time = active_rosbag_start_time + self.bag_rollover_time
        bag_finish_time_remaining = bag_finish_time - time.time()
        rospy.loginfo("Bag finish time remaining: %f" % bag_finish_time_remaining)

        # Emit some data to the test topic
        sleep_between_message = (bag_finish_time_remaining * 0.5)  / self.total_test_messages
        rospy.loginfo("Sleep between messages: %f" % sleep_between_message)
        for x in range(self.total_test_messages):
            print("In run record=======")
            self.test_publisher.publish("Test message %d" % x)
            print(x)
           # time.sleep(sleep_between_message)

        # Wait for current bag to finish recording and roll over
        bag_finish_time_remaining = bag_finish_time - time.time()
        rospy.loginfo("Bag finish time remaining after publish: %f" % bag_finish_time_remaining)

        # Add 0.5s as it takes some time for bag rotation to occur
        time.sleep(bag_finish_time_remaining) 

        # Send a goal to upload the bag data to S3
        # Create an Action client to send the goal
        self.action_client = actionlib.SimpleActionClient(ACTION, RollingRecorderAction)
        res = self.action_client.wait_for_server()
        self.assertTrue(res, 'Failed to connect to rolling recorder action server')

        # Create the goal and send through action client
        s3_folder = 'test_rr/'
        s3_subfolder = ''.join([random.choice(string.ascii_letters + string.digits) for _ in range(8)])  
        s3_destination = os.path.join(s3_folder, s3_subfolder)

        return (start_time, s3_destination)

    def send_rolling_recorder_upload_goal(self, s3_destination, start_time):
        latest_bag = self.get_latest_bag_by_regex("*.bag")
        print(latest_bag)
        print("++++++++++++++")
        end_time = rospy.Time.now()
        goal = RollingRecorderGoal(
            destination=s3_destination,
            start_time=start_time,
            end_time=end_time
        )
        self.action_client.send_goal(goal)
        res = self.action_client.wait_for_result(rospy.Duration.from_sec(GOAL_COMPLETION_TIMEOUT_SEC))
        self.assertTrue(res, "Rolling Recorder Goal timed out")
        result = self.action_client.get_result()
        self.assertEquals(result.result.result, RESULT_SUCCESS)

        s3_key = os.path.join(s3_destination, os.path.basename(latest_bag))
        with tempfile.NamedTemporaryFile() as f:
            self.s3_client.download_file(self.s3_bucket_name, s3_key, f.name)
            bag = rosbag.Bag(f.name)
            print("=======================")
            print(bag)
            print("=======================")
            total_bag_messages = 0
            for _, msg, _ in bag.read_messages():
                print("=======================")
                print(total_bag_messages)
                print("=======================")
                total_bag_messages += 1
            
            self.assertEquals(total_bag_messages, self.total_test_messages)

if __name__ == '__main__':
    rostest.rosrun(PKG, NAME, TestRollingRecorderUploadOnGoal, sys.argv)
