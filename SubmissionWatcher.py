import praw
from prawcore.exceptions import PrawcoreException
import config
import re
import logging
import time
from multiprocessing import Process, Queue, Event
from TaskExecution import Task
import spotipy


def dump_dict(to_dump):
    result = {}
    for key in to_dump.keys():
        result[key] = to_dump[key]
    time.sleep(.1)
    return result


# class to be passed to the task executor which will create a playlist for anyone to edit
class OpenPlaylist(Task):
    # initialize with the title of the playlist
    def __init__(self, title: str):
        self.title = title
        self.playlist = None

    def do_spotify_task(self, spotify: spotipy.Spotify, logger: logging.Logger):
        # create the spotify playlist
        self.playlist = spotify.user_playlist_create(config.SPOTIFY_USERNAME, self.title, public=True)
        logger.debug(f"Created a playlist of title {self.title}")
        # change the details of the playlist to be collaborative
        spotify.user_playlist_change_details(config.SPOTIFY_USERNAME, self.playlist['id'], self.playlist['name'], False,
                                             True)
        logger.debug(f"Made playlist {self.title} open to contribute to")

    def do_reddit_task(self, reddit: praw.Reddit, logger: logging.Logger, submission):
        # make sure our playlist is not none
        if self.playlist is None:
            logger.error("Playlist is none. This should not happen. TF")
            return

        # post the comment containing the link to the spotify playlist
        comment = submission.reply(
            f"{self.playlist['external_urls']['spotify']} is a collaborative playlist called {self.title}\n")
        logger.debug(f"Created comment on {submission.title}")
        # pin the comment
        comment.mod.distinguish(sticky=True)
        logger.debug("Pinned comment")


class BotMonitoredPlaylist(Task):

    def __init__(self, title: str, upvotes_needed: int, submission_monitor):
        self.title = title
        self.upvotes_needed = upvotes_needed
        self.playlist = None
        self.submission_monitor = submission_monitor

    def do_spotify_task(self, spotify: spotipy.Spotify, logger: logging.Logger):
        self.playlist = spotify.user_playlist_create(config.SPOTIFY_USERNAME, self.title, public=True)
        logger.debug(f"Created a playlist of title {self.title}")

    def do_reddit_task(self, reddit: praw.Reddit, logger: logging.Logger, submission):
        # make sure our playlist is not none
        if self.playlist is None:
            logger.error("Playlist is none. This should not happen. TF")
            return

        logger.debug("Appending playlist link")
        data = self.submission_monitor[submission.id]
        data.append(self.playlist['external_urls']['spotify'])
        self.submission_monitor[submission.id] = data
        # post the comment containing the link to the spotify playlist
        comment = submission.reply(f'''{self.playlist['external_urls']['spotify']} is a playlist called {self.title}  
                                   To make a submission comment  
                                   \"!add <song name> by <artist>\"  
                                   To vote on a submission comment \"!vote\"  
                                   This submission requires {self.upvotes_needed} votes to add a song to the playlist''')
        logger.debug(f"Created comment on {submission.title}")
        # pin the comment
        comment.mod.distinguish(sticky=True)
        logger.debug("Pinned comment")


class SubmissionWatcher(Process):
    def __init__(self, task_queue: Queue, monitor_submission):
        # initialize our variables
        super(SubmissionWatcher, self).__init__()
        self.reddit = praw.Reddit(client_id=config.REDDIT_ID, client_secret=config.REDDIT_SECRET,
                                  username=config.USERNAME,
                                  password=config.REDDIT_PASSWORD, user_agent="LetsMakeAPlaylist")

        self.subreddit = self.reddit.subreddit(config.SUBREDDIT)
        self.task_queue = task_queue
        self.pattern = re.compile("\[.*?\]")
        self.monitor_submission = monitor_submission

        self.logger = logging.Logger(__name__)
        self.logger.setLevel(logging.DEBUG)
        file_handler = logging.FileHandler(__name__ + ".log")
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # self.monitor_file = open("submissions.db", "a")

    def end(self):
        self.terminate()

    def monitor_subreddit(self):
        # for every submission in the subreddit
        for submission in self.subreddit.stream.submissions(skip_existing=True):
            self.logger.debug("New submission")
            # look in the title for the pattern of [any text]
            search = self.pattern.findall(submission.title)
            # if the title includes two brackets for the mode and title continue
            if len(search) > 1:
                self.logger.debug(f"Valid submission so far with title {submission.title}")

                # the mode is the first square brackets
                mode = str(search[0][1:-1]).lower().replace(" ", "")
                # get the title of the playlist
                title = search[1][1:-1]
                # if the mode is not open or auto= then ignore the post
                if mode != "open" and not mode.startswith("auto="):
                    self.logger.debug("Invalid mode for the submission")
                    continue

                # if the mode is open then create a collaborative playlist
                # task and put it in the queue for the task executor
                if mode == "open":
                    self.task_queue.put([OpenPlaylist(title), submission])
                    self.logger.debug("Put open playlist on queue for task execution")
                    continue

                # try to get the number of upvotes needed to add a song to the playlist
                # if the syntax is invalid or someone fucked up then default to 10
                num_upvotes_needed = -1
                try:
                    num_upvotes_needed = int(mode.split("=")[1])
                except Exception:
                    num_upvotes_needed = 10

                self.logger.debug(f"Auto playlist with upvotes needed of {num_upvotes_needed}")
                # add the submission to the list to monitor for comments
                self.monitor_submission[submission.id] = [num_upvotes_needed]
                self.logger.debug(f"Writing \"{submission.id}:{num_upvotes_needed}\"")
                task = BotMonitoredPlaylist(title, num_upvotes_needed, self.monitor_submission)
                self.task_queue.put([task, submission])
                self.logger.debug(f"Logged task to make bot monitored playlist")

    def run(self) -> None:
        running = True
        while running:
            try:
                self.monitor_subreddit()
            except KeyboardInterrupt:
                running = False
                self.logger.debug("Caught key interrupt exception")
            except PrawcoreException as e:
                self.logger.warning("Caught prawcore exception" + str(e))
                time.sleep(10)
