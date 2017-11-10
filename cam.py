#!/usr/bin/python3

import boto3
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient

import picamera

import time
import json
from io import BytesIO

CHANGE_THRESHOLD = 0.005
SLEEP_TIME = 3

CLIENT_ID = 'pyzcam'
PUBLISH_TOPIC = CLIENT_ID + '/out'
SUBSCRIBE_TOPIC = CLIENT_ID + '/in'
AWS_IOT_ENDPOINT = '<YOUR_AWS_IOT_ENDPOINT>'
REKOGNITION_COLLECTION_ID = 'security-camera'
S3_BUCKET = '<YOUR_S3_BUCKET>'
S3_IMAGE_KEY = 'pizero/image-{}.jpg'
S3_SEEN_KEY = 'pizero/seen.json'

s3 = boto3.client('s3')
rekognition = boto3.client('rekognition')

# Create an in-memory stream
image = BytesIO()
camera = picamera.PiCamera()
# camera.start_preview()


def enable_camera():
    print('Camera enabled')
    use_camera.size = 0
    use_camera.camera_enabled = True


def disable_camera():
    print('Camera disabled')
    use_camera.camera_enabled = False


def index_face(name):
    print('Indexing {}...'.format(name))
    take_picture(camera, image)
    key=upload_image_and_get_key(image)
    response=rekognition.index_faces(
        CollectionId=REKOGNITION_COLLECTION_ID,
        Image={
            'S3Object': {
                'Bucket': S3_BUCKET,
                'Name': key,
            }
        },
        ExternalImageId=name,
        DetectionAttributes=['ALL']
    )
    print(json.dumps(response, indent=4))


def message_received(client, userdata, message):
    print('Received a new message: ')
    print(message.payload)
    print('from topic: ')
    print(message.topic)
    print('--------------\n\n')
    payload=json.loads(message.payload.decode('utf-8'))
    if 'camera' in payload:
        if payload['camera'] == 'enable':
            enable_camera()
        elif payload['camera'] == 'disable':
            disable_camera()
        elif payload['camera'] == 'use':
            use_camera(once=True)
        else:
            print('Unknown camera state: {}'.format(payload['camera']))
    elif 'index' in payload:
        name=payload['index'].capitalize()
        index_face(name)
    else:
        print('Unknown command: {}'.format(json.dumps(payload, indent=4)))


def take_picture(camera, image):
    image.seek(0)
    camera.capture(image, 'jpeg')


def use_camera(once=False):

    take_picture(camera, image)

    if not once:
        previous_size=use_camera.size
        use_camera.size=image.tell()
        if (previous_size > 0):
            size_change=abs(1 - use_camera.size / previous_size)
        else:
            size_change=0
        print('size: {0} - previous: {1} - change: {2}'.format(use_camera.size,
                                                           previous_size, size_change))

    if (once or size_change > CHANGE_THRESHOLD):
        key=upload_image_and_get_key(image)
        analyse_image(key)


def upload_image_and_get_key(image):
    print('Uploading image to Amazon S3...')
    image.seek(0)
    key=S3_IMAGE_KEY.format(time.strftime('%Y%m%d%H%M%S'))
    print('key = {}'.format(key))
    response=s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=image
    )
    print(json.dumps(response, indent=4))
    return key


def upload_seen(file):
    print('Uploading file to Amazon S3...')
    print('key = {}'.format(S3_SEEN_KEY))
    response=s3.put_object(
        Bucket=S3_BUCKET,
        Key=S3_SEEN_KEY,
        Body=file
    )
    print(json.dumps(response, indent=4))


def analyse_image(key):
    # Use Amazon Rekognition
    print('Calling Amazon Rekognition...')
    seen = {}
    seen['Image'] = {
        'Bucket': S3_BUCKET,
        'Key': key,
    }
    print('Looking for labels...')
    response=rekognition.detect_labels(
        Image={
            'S3Object': {
                'Bucket': S3_BUCKET,
                'Name': key,
            }
        },
        MaxLabels=5,
        MinConfidence=70,
    )
    seen['Labels'] = response['Labels']
    print(json.dumps(seen['Labels'], indent=4))
    if any('Person' in l['Name'] for l in response['Labels']):
        # There is at least a person
        print('Looking for faces...')
        response=rekognition.detect_faces(
            Image={
                'S3Object': {
                    'Bucket': S3_BUCKET,
                    'Name': key,
                }
            },
            Attributes=['ALL']
        )
        seen['FaceDetails'] = response['FaceDetails']
        print(json.dumps(seen['FaceDetails'], indent=4))
        if len(response['FaceDetails']) > 0:
            # At least one face found...
            print('Looking for celebrities...')
            response=rekognition.recognize_celebrities(
                Image={
                    'S3Object': {
                    'Bucket': S3_BUCKET,
                    'Name': key,
                    }
                }
            )
            seen['CelebrityFaces'] = response['CelebrityFaces']
            print(json.dumps(seen['CelebrityFaces'], indent=4))
            print('Looking for known faces...')
            response=rekognition.search_faces_by_image(
                CollectionId=REKOGNITION_COLLECTION_ID,
                Image={
                    'S3Object': {
                    'Bucket': S3_BUCKET,
                    'Name': key,
                    }
                }
            )
            seen['FaceMatches'] = response['FaceMatches']
            print(json.dumps(seen['FaceMatches'], indent=4))

    upload_seen(json.dumps(seen))


def main():

    print('Connecting to AWS IoT...')
    myMQTTClient=AWSIoTMQTTClient(CLIENT_ID, useWebsocket=True)
    myMQTTClient.configureCredentials('./rootCA.txt')
    myMQTTClient.configureEndpoint(AWS_IOT_ENDPOINT, 443)  # WebSockets
    myMQTTClient.connect()
    print('Publishing to AWS IoT...')
    myMQTTClient.publish(PUBLISH_TOPIC, 'myPayload', 0)
    print('Subscribing to AWS IoT...')
    myMQTTClient.subscribe(SUBSCRIBE_TOPIC, 1, message_received)

    print('Ready to Go!')

    use_camera.camera_enabled = False

    while True:
        # Camera warm-up time
        time.sleep(SLEEP_TIME)

        if use_camera.camera_enabled:
            use_camera()


main()
