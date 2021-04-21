#!/usr/bin/env python3

__author__ = "tarik0"

import pickle
from datetime import datetime
from json import loads
from random import uniform
from threading import Event, Thread
from time import sleep

from requests import Session, Response

# You can get it from ex. https://subdomain.almscloud.com/Activity/Index/COURSE_ID
COURSE_ID = ""
# Your ALMS username.
USERNAME = ""
# Your ALMS password.
PASSWORD = ""
# Your ALMS host.
ALMS_HOST = "subdomain.almscloud.com"


def iso_format(dt):
    """ Convert datetime object to Javascript like ISO date string. """
    try:
        utc = dt + dt.utcoffset()
    except TypeError as e:
        utc = dt
    isostring = datetime.strftime(utc, '%Y-%m-%dT%H:%M:%S.{0}Z')
    return isostring.format(int(round(utc.microsecond / 1000.0)))


class ALMSClient:
    """
    ALMSClient:
        A HTTP wrapper to communicate with the ALMS.
    """

    PING_INTERVAL_SEC = 5

    def __init__(self, username: str, password: str):
        """ Construct the class. """
        self.__username = username
        self.__password = password
        self.__disposed = False
        self.__first_ping_event = Event()
        self.__auth_event = Event()
        self.__ping_timer = Thread(target=self.__ping_interval, args=())
        self.__session = Session()
        self.__session.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/89.0.4389.90 Safari/537.36 ",
            "sec-ch-ua": '"Chromium";v="89", ";Not A Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "Upgrade-Insecure-Requests": "1",
            "Connection": "close"
        }

    def login(self, timeout=15):
        """ Login to the ALMS. """
        # Get necessary cookies.
        res = self.__session.get(f"https://{ALMS_HOST}/Account/LoginBefore")
        if res.status_code != 200:
            res.raise_for_status()

        # Start the ping interval and wait for the first ping to succeed.
        self.__ping_timer.start()
        self.__first_ping_event.wait(timeout)

        # Enter username.
        res = self.__session.post(
            f"https://{ALMS_HOST}/Account/LoginBefore?returnUrl=%2FHome%2FIndex",
            data={
                "LocationName": "",
                "Latitude": "",
                "Longitude": "",
                "LoginChannel": "",
                "TimeZoneOffset": -180,  # This is hardcoded on the website too.
                "UserName": self.__username
            }
        )
        if res.status_code != 200:
            res.raise_for_status()

        # Enter password.
        self.__session.cookies.set("CookUserName", self.__username)
        res = self.__session.post(
            f"https://{ALMS_HOST}/?returnUrl=%2FHome%2FIndex",
            data={
                "LocationName": "",
                "Latitude": "",
                "Longitude": "",
                "LoginChannel": "",
                "TimeZoneOffset": -180,  # This is hardcoded on the website too.
                "UserName": "",
                "Password": self.__password
            }
        )
        if res.status_code != 200:
            res.raise_for_status()

        self.__auth_event.set()
        self.save_to_file()

    def login_via_cache(self):
        """ Login with the previous saved cache. """
        with open(f"{self.__username}.cache", "rb") as f:
            self.__session = pickle.load(f)

    def save_to_file(self):
        """ Save session to a file to re-use it without authenticating. """
        with open(f"{self.__username}.cache", "wb") as f:
            pickle.dump(self.__session, f)

    def get_class_progress(self, course_id: str) -> dict:
        """ Get class progresses. """
        res = self.__session.get(f"https://{ALMS_HOST}/Activity/Index/{course_id}")
        if res.status_code != 200:
            res.raise_for_status()

        tmp = loads(res.text.split("var datasource = ")[1].split("};")[0] + "}")
        return tmp

    def get_flow_data(self, activity_id: str, attempt_id: str) -> dict:
        """ Get flow player data. """
        res = self.__session.post(
            f"https://{ALMS_HOST}/Video/ManageInteraction?id={activity_id}&attemptId={attempt_id}",
            data={
                "/Video/ManageInteraction?id": activity_id,
                "attemptId": attempt_id
            }
        )
        if res.status_code != 200:
            res.raise_for_status()

        return res.json()

    def submit_track(self, activity_id: str, enroll_id: str):
        """ Simulate that we have finished the activity. """
        # Get attempt id from the page.
        res = self.__session.get(
            f"https://{ALMS_HOST}/Video/Play",
            data={
                "id": activity_id,
                "eId": enroll_id,
                "isPartialView": True
            }
        )
        if res.status_code != 200:
            res.raise_for_status()

        # Parse the output and get attempt id.
        attempt_id = res.text.split("attemptId=")[1].split("',")[0]

        # Get video data.
        flow_data = self.get_flow_data(activity_id, attempt_id)
        video_duration = flow_data["Meta"]["Duration"]

        # That means we don't have a video to watch.
        if video_duration == 0:
            return "Derse video yüklenmemiş!"

        # Send tracking information.
        date = iso_format(datetime.utcnow())
        res = self.__session.post(
            f"https://{ALMS_HOST}/Video/SaveTracking?TrackingData=&id={activity_id}&AttemptId={attempt_id}&EnrollId={enroll_id}",
            data={
                "date": date,
                "duration": video_duration,
                "response": None,
                "totalPartSec": video_duration,
                "viewParts": f"[\"0-{video_duration}\"]"
            }
        )
        if res.status_code != 200:
            res.raise_for_status()

        return res.text

    def dispose(self):
        """ Close the ping interval and dispose the class. """
        if self.__first_ping_event.is_set():
            self.__disposed = True
            self.__ping_timer.join()

    def __ping_interval(self):
        """ We gotta send a ping request per 5 seconds. """
        while not self.__disposed:
            self.__send_ping()
            if not self.__first_ping_event.is_set():
                self.__first_ping_event.set()
            sleep(ALMSClient.PING_INTERVAL_SEC)
            if not self.__auth_event.is_set():
                self.__auth_event.wait()

    def __send_ping(self) -> Response:
        """ Send ping request. """
        tmp = uniform(0, 1)
        res = self.__session.get(f"https://{ALMS_HOST}/System/Ping?r={tmp}")
        if res.status_code != 200:
            res.raise_for_status()

        return res


if __name__ == '__main__':
    # Get inputs.
    COURSE_ID = input("Kurs ID'si: ")
    USERNAME = input("ALMS Kullanıcı Adınız: ")
    PASSWORD = input("ALMS Şifreniz: ")

    # Authenticate with ALMS
    print(f"{USERNAME} olarak ALMS'ye giriş yapılyor...")
    alms = ALMSClient(USERNAME, PASSWORD)
    alms.login()

    print("Başarıyla giriş yapıldı! Ders bilgileri alınıyor...")

    unfinished_lessons = []
    finished_lessons = []

    # Get lesson counts.
    progresses = alms.get_class_progress(COURSE_ID)

    k = progresses["activities"]
    for activity in progresses["activities"]:
        # Skip non-video lessons.
        if not ("status" in activity) or \
                not ("type" in activity) or \
                not activity["isActive"] or \
                activity["type"] != "Video" or \
                activity["completionType"] != "View":
            continue

        # Check progress
        if activity["status"]["progress"] >= 90:
            finished_lessons.append(activity)
        else:
            unfinished_lessons.append(activity)

    print("Programın çalışması için derslerin web sayfalarını önceden görüntülemeniz lazımdır!")

    # Print lesson statuses.
    print("\nDers bilgileri alındı;")
    print(f"    Bitirilmiş ders sayısı:   {len(finished_lessons)}")
    print(f"    Bitirilmemiş ders sayısı: {len(unfinished_lessons)}\n")

    # Print lessons
    print("Bitirilmiş dersler;")
    for activity in finished_lessons:
        print(f"    {activity['addedDate']} | {activity['UserName']} - {activity['name']}")

    print("\nBitirilmemiş dersler;")
    for activity in unfinished_lessons:
        print(f"    {activity['addedDate']} | {activity['UserName']} - {activity['name']}")

    # Finish lessons
    print("\nDersler bitiriliyor;")
    for activity in unfinished_lessons:
        enroll_id = activity["enrollmentId"]
        activity_id = activity["id"]
        result = alms.submit_track(activity_id, enroll_id)
        print(f"    Bitirildi - {activity['addedDate']} | {activity['UserName']} - {activity['name']}: {result}")
        sleep(1)

    print("\nBütün dersler bitirildi!")
    alms.dispose()
