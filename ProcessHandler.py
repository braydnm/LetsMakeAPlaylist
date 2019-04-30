from multiprocessing import Manager, Queue
import signal
from SubmissionWatcher import *
from TaskExecution import *
from CommentWatcher import *
import pickle
import os


def dump_queue(to_dump):
    result = []

    for i in iter(to_dump.get, None):
        result.append(i)
    time.sleep(.1)
    return result


def dump_dict(to_dump):
    result = {}
    for key in to_dump.keys():
        result[key] = to_dump[key]
    time.sleep(.1)
    return result


if __name__ == '__main__':
    original_signal = signal.signal(signal.SIGINT, signal.SIG_IGN)
    manager = Manager()
    spotify_queue = Queue()
    if os.path.exists("queue.saved"):
        with open("queue.saved", "rb") as f:
            loaded = pickle.load(f)
            for task in loaded:
                spotify_queue.put(task)
            time.sleep(.1)

    print("Starting spotify process")
    spotify_process = TaskExecution(spotify_queue)
    spotify_process.start()

    monitor_dict = manager.dict()
    if os.path.exists("submissions.db"):
        with open("submissions.db", "rb") as f:
            submissions = pickle.load(f)

        for key in submissions.keys():
            monitor_dict[key] = submissions[key]
        time.sleep(.1)

    print("Starting submission watcher process")
    submission_watcher = SubmissionWatcher(spotify_queue, monitor_dict)
    submission_watcher.start()

    print("Starting comment watcher")
    comment_watcher = CommentWatcher(spotify_queue, monitor_dict)
    comment_watcher.start()

    signal.signal(signal.SIGINT, original_signal)
    try:
        spotify_process.join()
    except KeyboardInterrupt as e:
        print("Exiting")
        spotify_process.clean_exit()
        submission_watcher.end()
        comment_watcher.terminate()
        spotify_process.terminate()
        submission_watcher.terminate()
        print("All processes terminated\nDumping queue")
        time.sleep(.1)
        queue = dump_queue(spotify_queue)
        print("Finished dumping queue to list")
        submissions = dump_dict(monitor_dict)
        print("Finished dumping dict")
        with open("queue.save", "wb") as f:
            pickle.dump(queue, f)
        with open("submissions.db", "wb") as f:
            pickle.dump(submissions, f)
        print("Finished exiting")
