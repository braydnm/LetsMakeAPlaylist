from multiprocessing import Process, Queue, Event
import spotipy
import spotipy.util
import config
import logging
from abc import ABC, abstractmethod
import praw
import time


# Base task class which can be put in the queue to be executed
class Task(ABC):
    @abstractmethod
    def do_spotify_task(self, spotify: spotipy.Spotify, logger: logging.Logger):
        pass

    @abstractmethod
    def do_reddit_task(self, reddit: praw.Reddit, logger: logging.Logger, submission):
        pass


class TaskExecution(Process):

    # create the spotify object
    def make_spotify(self) -> spotipy.Spotify:
        try:
            self.logger.debug("Creating the Spotify instance")
            sp = spotipy.Spotify(auth=spotipy.util.prompt_for_user_token(config.USERNAME, config.SPOTIFY_SCOPE,
                                                                         config.SPOTIFY_CLIENT_ID,
                                                                         config.SPOTIFY_CLIENT_SECRET,
                                                                         config.SPOTIFY_CALLBACK,
                                                                         cache_path=".LetsMakeAPlaylistBot.cache"))
            sp.trace = False

        except Exception as e:
            self.logger.error("Error creating the spotify service... Exiting")
            self.logger.error(e)
            exit(1)

        return sp

    def __init__(self, queue: Queue):
        # initialize the parent object
        super(TaskExecution, self).__init__()

        # create our logger
        self.logger = logging.Logger(__name__)
        self.logger.setLevel(logging.DEBUG)
        file_handler = logging.FileHandler(__name__ + ".log")
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # create the objects to interact with spotify and reddit
        self.spotify = self.make_spotify()
        self.reddit = praw.Reddit(client_id=config.REDDIT_ID, client_secret=config.REDDIT_SECRET,
                                  username=config.USERNAME,
                                  password=config.REDDIT_PASSWORD, user_agent="LetsMakeAPlaylist")

        # create our queue and the exit event
        self.job_queue = queue
        self.exit_event = Event()

    # exit the task execution cleanly
    def clean_exit(self):
        self.logger.debug("Attempting to exit gracefully")
        # put nothing in the queue in case the queue.get() function is blocking
        self.job_queue.put(None)
        # set the event to exit
        self.exit_event.set()
        self.logger.debug("Waiting to complete the current task and then exiting")
        self.job_queue.put(None)

    def run(self) -> None:
        # while our exit flag is not set
        while not self.exit_event.is_set():
            # get the next job
            job = self.job_queue.get()
            # if the job is None it was put here to exit so continue
            if job is None:
                continue

            # complete the tasks required
            while True:
                try:
                    job[0].do_spotify_task(self.spotify, self.logger)
                    self.logger.debug("Completed a spotify task")
                    job[0].do_reddit_task(self.reddit, self.logger, job[1])
                    break
                except Exception as e:
                    self.logger.error(f"Failed to complete task with error {e}")
                    time.sleep(4)
