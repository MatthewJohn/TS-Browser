#!/usr/bin/python

# Copyright (c) 2016 - Matt Comben
#
# This file is part of TransportStreamBrowser.
#
# TransportStreamBrowser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# TransportStreamBrowser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License

import os
import subprocess
import json
import shutil
import tempfile
import time
import threading
import fnmatch
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from flask import Flask, render_template
import glob
import humanize


TS_DIR = '/home/matthew/transportstream'


class FileDoesNotExist(Exception):
    pass


class InvalidFilename(Exception):
    pass


class JobStatus(object):
    QUEUED = 1
    RUNNING = 2
    FAILED = 3
    COMPLETE = 4


class JobType(object):
    METADATA = 1
    SCREENSHOT = 2
    SHUTDOWN = 3


def run_command(command_args, cwd=None):
    """Run system command"""
    command_process = subprocess.Popen(
        command_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd)
    rc = command_process.wait()
    stdout = command_process.stdout.read()
    stderr = command_process.stderr.read()
    return (rc, stdout, stderr)


class Worker(object):
    QUEUE = []
    JOB_REFERENCE = {}

    @staticmethod
    def add_job(path, job_type, object_ref, start=False):
        key = (path, job_type)
        if key not in Worker.QUEUE:
            if start:
                Worker.QUEUE.insert(0, key)
            else:
                Worker.QUEUE.append(key)
            Worker.JOB_REFERENCE[key] = object_ref
            object_ref.job_status[job_type] = JobStatus.QUEUED

    def __init__(self):
        self.active = True
        self.thread_ref = threading.Thread(target=self.run)

    def start(self):
        self.thread_ref.start()

    def run(self):
        while self.active:
            if not len(Worker.QUEUE):
                time.sleep(2)
            else:
                job = Worker.QUEUE[0]
                if job[1] == JobType.METADATA:
                    Worker.JOB_REFERENCE[job].generate_metadata()
                elif job[1] == JobType.SCREENSHOT:
                    Worker.JOB_REFERENCE[job].generate_screenshot()
                elif job[1] == JobType.SHUTDOWN:
                    self.active = False
                Worker.QUEUE.remove(job)
                del(Worker.JOB_REFERENCE[job])

    def shutdown(self):
        self.active = False
        class Fake(object):
            def __init__(self):
                self.job_status = {'shutdown': 0}
        Worker.add_job('shutdown', JobType.SHUTDOWN, Fake(), start=True)


class Inspector(object):

    CACHED_OBJECTS = {}

    @staticmethod
    def get_inspector(filename):
        if filename not in Inspector.CACHED_OBJECTS:
            Inspector.CACHED_OBJECTS[filename] = Inspector(filename)
        return Inspector.CACHED_OBJECTS[filename]

    def __init__(self, filename):
        self.filename = filename
        self.job_status = {
            JobType.SCREENSHOT: None,
            JobType.METADATA: None
        }

    def get_file_paths(self):
        if not os.path.isfile(self.filename):
            raise FileDoesNotExist('%s does not exist' % self.filename)

        filename = os.path.basename(self.filename)
        if filename.startswith('.'):
            raise InvalidFilename('%s starts with invalid character' % self.filename)
        if not filename.endswith('.ts'):
            raise InvalidFilename('%s does not end in \'ts\'' % self.filename)

        directory = os.path.dirname(self.filename)
        filename = os.path.basename(self.filename)
        web_dir = directory.replace(TS_DIR, '')
        if not web_dir.startswith('/'):
            web_dir = "/%s" % web_dir
        return {
            'dir': directory,
            'filename': filename,
            'metadata_file': '%s/.%s-meta' % (directory, filename),
            'screenshot': '%s/.%s-screenshot' % (directory, filename),
            'web_path': self.filename.replace(TS_DIR, ''),
            'web_dir': web_dir
        }

    def get_screenshot(self, force_update=False):
        paths = self.get_file_paths()

        if force_update or not os.path.isfile(paths['screenshot']):
            if force_update or self.job_status[JobType.SCREENSHOT] != JobStatus.FAILED:
                Worker.add_job(self.filename, JobType.SCREENSHOT, self)
            return self.job_status[JobType.SCREENSHOT]
        else:
            with open(paths['screenshot'], 'rb') as fh:
                data = fh.read()
            return data.encode('base64')

    def get_metadata(self, force_update=False):
        paths = self.get_file_paths()
        if force_update or not os.path.isfile(paths['metadata_file']):
            if force_update or self.job_status[JobType.METADATA] != JobStatus.FAILED:
                Worker.add_job(self.filename, JobType.METADATA, self)
            return self.job_status[JobType.METADATA]
        else:
            with open(paths['metadata_file'], 'r') as fh:
                data = json.loads(fh.read())
            return data

    def generate_metadata(self):
        try:
            self.job_status[JobType.METADATA] = JobStatus.RUNNING
            rc, output, stderr = run_command(['ffprobe', '-show_streams', '-show_format',
                                              '-show_chapters', '-show_programs', '-v', 'quiet',
                                              '-print_format', 'json', self.filename])
            assert (rc == 0)

            metadata = json.loads(output)
            paths = self.get_file_paths()
            with open(paths['metadata_file'], 'w') as fh:
                fh.write(json.dumps(metadata))
            self.job_status[JobType.METADATA] = JobStatus.COMPLETE
        except:
            self.job_status[JobType.METADATA] = JobStatus.FAILED

    def generate_screenshot(self, force_update=False):
        temp_dir = tempfile.mkdtemp()
        try:
            self.job_status[JobType.SCREENSHOT] = JobStatus.RUNNING
            rc, output, stderr = run_command(['cvlc', self.filename, '--rate', '1',
                                              '--video-filter', 'scene', '--vout',
                                              'dummy', '--start-time', '0', '--stop-time', '1',
                                              '--scene-format', 'png', '--scene-ratio', '10000000',
                                              '--scene-prefix', 'snap', '--scene-path', temp_dir,
                                              '--play-and-exit'])
            assert (rc == 0)
            assert len(os.listdir(temp_dir))
            src_screenshot = '%s/%s' % (temp_dir, os.listdir(temp_dir)[0])
            paths = self.get_file_paths()
            shutil.copyfile(src_screenshot, paths['screenshot'])
            assert os.path.isfile(paths['screenshot'])
            self.job_status[JobType.SCREENSHOT] = JobStatus.COMPLETE
            shutil.rmtree(temp_dir)
        except:
            self.job_status[JobType.SCREENSHOT] = JobStatus.FAILED
            shutil.rmtree(temp_dir)
            raise
        


class Searcher(object):

    def get_file_list(self):
        matches = []
        for root, dirnames, filenames in os.walk(TS_DIR):
            for filename in fnmatch.filter(filenames, '*.ts'):
                matches.append(os.path.join(root, filename))
        return matches

    def get_all_files_in_dir(self, directory):
        inspectors = {}
        for file_name in glob.glob('%s/*.ts' % directory):
            try:
                inspectors[file_name] = Inspector.get_inspector(file_name)
            except:
                pass
        return inspectors

    def get_all_dirs_in_dir(self, directory):
        directories = []
        for file_name in glob.glob('%s/*' % directory):
            if os.path.isdir(file_name) and file_name not in ('.', '..'):
                directories.append(file_name)
        return directories

    def get_all_inspector_objects(self):
        inspector_objects = {}
        for filename in self.get_file_list():
            inspector_objects[filename] = Inspector.get_inspector(filename)
        return inspector_objects

class MonitorHandler(FileSystemEventHandler):
    def on_deleted(self, event):
        if not event.is_directory:
            inspect_obj = Inspector.get_inspector(event.src_path)
            paths = inspect_obj.get_file_paths()
            if os.path.exists(paths['metadata_file']):
                os.unlink(paths['metadata_file'])

            if os.path.exists(paths['screenshot']):
                os.unlink(paths['screenshot'])

    def on_modified(self, event):
        if not event.is_directory:
            inspect_obj = Inspector.get_inspector(event.src_path)
            paths = inspect_obj.get_file_paths()
            if os.path.exists(paths['metadata_file']):
                os.unlink(paths['metadata_file'])

            if os.path.exists(paths['screenshot']):
                os.unlink(paths['screenshot'])
            inspect_obj.get_screenshot()
            inspect_obj.get_metadata()

    def on_moved(self, event):
        if not event.is_directory:
            inspect_obj = Inspector.get_inspector(event.dest_path)
            paths = inspect_obj.get_file_paths()
            if os.path.exists(paths['metadata_file']):
                os.unlink(paths['metadata_file'])

            if os.path.exists(paths['screenshot']):
                os.unlink(paths['screenshot'])
            inspect_obj.get_screenshot()
            inspect_obj.get_metadata()

    def on_created(self, event):
        if not event.is_directory:
            inspect_obj = Inspector.get_inspector(event.src_path)
            paths = inspect_obj.get_file_paths()
            if os.path.exists(paths['metadata_file']):
                os.unlink(paths['metadata_file'])

            if os.path.exists(paths['screenshot']):
                os.unlink(paths['screenshot'])
            inspect_obj.get_screenshot()
            inspect_obj.get_metadata()


class Monitor(object):

    def __init__(self):
        self.observer = Observer()
        handler = MonitorHandler()
        self.observer.schedule(handler, TS_DIR, recursive=True)

    def start(self):
        self.observer.start()

    def shutdown(self):
        self.observer.stop()   

class WebServer(object):
    def __init__(self):
        self.app = Flask(__name__)

        @self.app.route('/', defaults={'path': './'})
        @self.app.route('/<path:path>')
        def process_request(path):
            full_path = os.path.normpath(os.path.join(TS_DIR, './%s' % path))
            if os.path.isfile(full_path):
                return self.ts_file(path)
            elif os.path.isdir(full_path):
                return self.dir_listing(path)
            else:
                return self.not_found(path)


    def dir_listing(self, path):
        full_path = os.path.normpath(os.path.join(TS_DIR, './%s' % path))
        searcher = Searcher()
        subdirectories = searcher.get_all_dirs_in_dir(full_path)
        subdirectories = [subdirectory.replace('%s/' % TS_DIR, '') for subdirectory in subdirectories]
        files = searcher.get_all_files_in_dir(full_path)
        file_objects = {}
        for file_path in files:
            inspector = Inspector.get_inspector(file_path)
            file_objects[inspector.get_file_paths()['filename']] = inspector
        parent = os.path.normpath(os.path.join(full_path, '..'))
        if TS_DIR in parent:
            if parent == TS_DIR:
                parent = '/'
            else:
                parent = os.path.normpath(os.path.join(path, '..')).replace(TS_DIR, '')
                if not parent.startswith('/'):
                    parent = '/%s' % parent
        else:
            parent = None
        return render_template('dir_listing.html', subdirectories=subdirectories,
                               files=file_objects, parent=parent)

    def ts_file(self, path):
        full_path = os.path.normpath(os.path.join(TS_DIR, './%s' % path))
        inspector = Inspector.get_inspector(full_path)
        parent = inspector.get_file_paths()['web_dir']
        metadata = inspector.get_metadata()

        video_streams = []
        audio_streams = []
        other_streams = []
        if metadata not in range(1, 5) and 'streams' in metadata:
            for index, stream in enumerate(metadata['streams']):
                if 'codec_type' in stream and stream['codec_type'] == 'video':
                    video_streams.append(index)
                    try:
                        if 'avg_frame_rate' in stream:
                            stream['avg_frame_rate_norm'] = eval(stream['avg_frame_rate'])
                    except ZeroDivisionError:
                        pass
                elif 'codec_type' in stream and stream['codec_type'] == 'audio':
                    audio_streams.append(index)
                else:
                    other_streams.append(index)

            if 'format' in metadata and 'size' in metadata['format']:
                metadata['format']['size_hr'] = humanize.naturalsize(metadata['format']['size'],
                                                                     gnu=True)


        return render_template('ts_file.html', inspector=inspector,
                               screenshot=inspector.get_screenshot(),
                               metadata=metadata, parent=parent,
                               job_status=JobStatus(),
                               video_streams=video_streams, audio_streams=audio_streams,
                               other_streams=other_streams)

    def not_found(self, path):
        return render_template('not_found.html', file_path=path)

    def start(self):
        self.app.run(threaded=True, debug=True)


if __name__ == "__main__":
    worker = Worker()
    worker.start()
    monitor = Monitor()
    #monitor.start()
    webserver = WebServer()
    try:
        webserver.start()
    except KeyboardInterrupt:
        print 'Shutting down monitor'
        monitor.shutdown()
        print 'Shutting down worker'
        worker.shutdown()
        print 'Finished shutting down'
        raise
