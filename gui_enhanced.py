from threading import Lock
from PyQt5.QtGui import *
from PyQt5.QtWidgets import (QMainWindow, QWidget, QPushButton, QVBoxLayout, QApplication, QLabel,
                             QGridLayout, QHBoxLayout, QComboBox, QCalendarWidget, QListWidget,
                             QSlider, QMessageBox, QRadioButton, QButtonGroup, QDialog)
from PyQt5.QtCore import *
import datetime
import cv2
import copy
import pandas as pd
from tkinter.filedialog import askdirectory
from tkinter import Tk, messagebox
import math
import time
import traceback, sys
import shutil
from data_utils import *
FLAG_COMPLETE = False
FLAG_PLAYING = False
FLAG_EVENT_START = False
FLAG_DATABASE_SAFE = True

import threading
from queue import Queue
import numpy as np
from tqdm import tqdm

class imageThread(QThread):
    changePixmap = pyqtSignal(QImage)
    frames_queue = Queue()
    event_dict = {0: "Knock Down", 1: "Attemp", 2: "Success", 3: "Successful Lick", 4: "Discard this event"}
    def run(self):
        global FLAG_EVENT_START
        while True:
            if self.frames_queue.qsize() > 0:
                cvImg = self.frames_queue.get()
                if FLAG_EVENT_START:
                    for i in range(len(list(self.event_dict.keys()))):
                        cvImg = cv2.putText(cvImg, str('%d: ' % i) + self.event_dict[i], (800, 100 + i * 20),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), lineType=cv2.LINE_AA)
                height, width, channel = cvImg.shape
                bytesPerLine = 3 * width
                qImg = QImage(cvImg.data, width, height, bytesPerLine, QImage.Format_RGB888)
                self.changePixmap.emit(qImg)

class WorkerSignals(QObject):
    '''
    Defines the signals available from a running worker thread.

    Supported signals are:

    finished
        No data

    error
        `tuple` (exctype, value, traceback.format_exc() )

    result
        `object` data returned from processing, anything

    progress
        `int` indicating % progress

    '''
    finished = pyqtSignal(object)
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(int)


class Worker(QRunnable):
    '''
    Worker thread

    Inherits from QRunnable to handler worker thread setup, signals and wrap-up.

    :param callback: The function callback to run on this worker thread. Supplied args and
                     kwargs will be passed through to the runner.
    :type callback: function
    :param args: Arguments to pass to the callback function
    :param kwargs: Keywords to pass to the callback function

    '''

    def __init__(self, fn, *args, **kwargs):
        super(Worker, self).__init__()

        # Store constructor arguments (re-used for processing)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

        # Add the callback to our kwargs
        self.kwargs['progress_callback'] = self.signals.progress

    @pyqtSlot()
    def run(self):
        '''
        Initialise the runner function with passed args, kwargs.
        '''

        # Retrieve args/kwargs here; and fire processing using them
        try:
            result = self.fn(*self.args, **self.kwargs)
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)  # Return the result of the processing
        finally:
            self.signals.finished.emit(result)  # Done


class Overlay(QWidget):

    def __init__(self, parent=None):

        QWidget.__init__(self, parent)
        palette = QPalette(self.palette())
        palette.setColor(palette.Background, Qt.transparent)
        self.setPalette(palette)

    def paintEvent(self, event):

        painter = QPainter()
        painter.begin(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(event.rect(), QBrush(QColor(255, 255, 255, 200)))
        painter.setPen(QPen(Qt.NoPen))

        for i in range(6):
            if (self.counter / 5) % 6 == i:
                painter.setBrush(QBrush(QColor(190 + i*10, 0, 0)))
            else:
                painter.setBrush(QBrush(QColor(10, 10, 10)))
            painter.drawEllipse(
                int(self.width() / 2 + 30 * math.cos(2 * math.pi * i / 6.0) - 10),
                int(self.height() / 2 + 30 * math.sin(2 * math.pi * i / 6.0) - 10),
                20, 20)

        painter.end()

    def showEvent(self, event):
        self.timer = self.startTimer(50)
        self.counter = 0
        global FLAG_COMPLETE
        FLAG_COMPLETE = False

    def timerEvent(self, event):
        self.counter += 1
        self.update()
        global FLAG_COMPLETE
        if FLAG_COMPLETE:
            self.killTimer(self.timer)
            self.hide()

class StartWindow(QMainWindow):

    def __init__(self):
        self.inital_completed = False
        self.threadpool = QThreadPool()
        self.lock = Lock()
        self.video_stream = None

        root = Tk()
        root.withdraw()
        self.root_dir = askdirectory(initialdir=os.getcwd(), title="Select root directory containing all cage folders")
        if self.root_dir is ():
            raise AssertionError
        else:
            self.database_local_dir = os.path.join('database', 'homecage_database.sqlite')
            self.F = None
            super().__init__()

            self.widget_main = QWidget()
            self.play_speed = 0
            self.image_label = QLabel()
            self.image_label.resize(1280, 720)

            self.radio_group = [
                QRadioButton('Unlabeled'),
                QRadioButton('Labeled')
            ]

            self.components_left = [
                QLabel("Cage"), QComboBox(),
                QLabel("Animal"), QComboBox(),
                QLabel("Date"),
                QLabel("From"), QCalendarWidget(),
                QLabel("Till"), QCalendarWidget(),
                QLabel("Video List || Double click :)"), QListWidget(),
                QPushButton('Generate table')
            ]
            self.components_right_low = [
                QPushButton('Play(space)'),
                QPushButton('Speed(q): %d' % self.play_speed),
                QPushButton('Next Frame (d)'),
                QPushButton('Previous Frame (a)'),
                QPushButton('Start Labeling (s)'),
                QPushButton('Clean all labels')
            ]
            for i in range(len(self.components_right_low)):
                self.components_right_low[i].setDisabled(True)
            self.Playing_Flag = False
            self.layout_main = QGridLayout()
            self.layout_left = QVBoxLayout()
            self.layout_radio = QHBoxLayout()
            self.layout_right_high = QVBoxLayout()
            self.layout_right_low = QHBoxLayout()
            self.widget_main.setLayout(self.layout_main)
            for component in self.components_left:
                self.layout_left.addWidget(component)
            for component in self.components_right_low:
                self.layout_right_low.addWidget(component)
            for radio in self.radio_group:
                self.layout_radio.addWidget(radio)

            self.slider = QSlider(Qt.Horizontal)
            self.slider.setTickPosition(QSlider.TicksBothSides)
            self.slider.setTickInterval(10)
            self.slider.setSingleStep(1)
            self.slider.setValue(0)
            self.radio_group[0].setChecked(True)

            self.layout_right_high.addWidget(self.image_label)
            self.layout_right_high.addWidget(self.slider)
            self.components_left[6].setMaximumDate(datetime.datetime.now())
            self.components_left[8].setMaximumDate(datetime.datetime.now())
            self.min_date = datetime.datetime.now()
            self.max_date = datetime.datetime.now()

            self.layout_left.addLayout(self.layout_radio)
            self.layout_main.addLayout(self.layout_left, 0, 0, 4, 1)
            self.layout_main.addLayout(self.layout_right_high, 0, 2, 4, 4)
            self.layout_main.addLayout(self.layout_right_low, 4, 2, 5, 5)
            self.setCentralWidget(self.widget_main)
            self.overlay = Overlay(self.centralWidget())
            self.overlay.show()
            self.show()
            self.thread_get_cages()

            self.components_left[1].currentIndexChanged.connect(self.on_select_cage)
            self.components_left[3].currentIndexChanged.connect(self.on_select_animal)
            self.components_left[6].selectionChanged.connect(self.on_select_date_min)
            self.components_left[8].selectionChanged.connect(self.on_select_date_max)
            self.components_left[10].itemDoubleClicked.connect(self.on_select_video)
            self.components_left[10].setSelectionMode(QListWidget.SingleSelection)
            self.components_left[11].clicked.connect(self.on_table)

            self.slider.sliderMoved.connect(self.on_slider)
            self.slider.sliderReleased.connect(self.on_slider_release)

            self.components_right_low[0].clicked.connect(self.on_play)
            self.components_right_low[1].clicked.connect(self.on_speed)
            self.components_right_low[2].clicked.connect(self.on_next_frame)
            self.components_right_low[3].clicked.connect(self.on_previous_frame)
            self.components_right_low[4].clicked.connect(self.on_labeling)
            self.components_right_low[5].clicked.connect(self.on_clean_all)

            for i in range(len(self.radio_group)):
                self.radio_group[i].clicked.connect(lambda: self.on_radio(self.radio_group[i]))
            self.preload_size = 1500
            # self.preload_buffer = Queue()
            self.init_image = cv2.imread(os.path.join("pic", "init.jpg"))
            self.init_image = cv2.cvtColor(self.init_image, cv2.COLOR_BGR2RGB)
            self.init_image = cv2.resize(self.init_image, (1280, 720))
            self.th = imageThread()
            self.th.changePixmap.connect(self.update_image)
            self.th.start()
            self.th.frames_queue.put(self.init_image)
            self.animal = ""
            self.index = 0
            self.inital_completed = True
            self.start_frame = 0
            self.end_frame = 0
            self.event_dict = {0: "Knock Down", 1: "Attemp", 2: "Success", 3: "Successful Lick", 4: "Discard this event"}
            self.current_video_list_all = []
            self.current_video_list_unlabeled = []
            self.current_video_list_labeled = []
            self.video_path = None
            self.slider_queue = Queue()
            self.thread_update_slider()
            self.thread_update_database()
            # self.thread_preload_video()

    def keyPressEvent(self, event):
        global FLAG_EVENT_START
        global FLAG_PLAYING
        self.components_right_low[0].setFocus()
        key_id = (event.key() & 0xFF) + 32
        if self.video_stream is not None:
            if FLAG_EVENT_START and key_id in range(80, 90):
                event_id = key_id - 80
                self.on_saving(event_id)
            if key_id == ord(" "):
                self.on_play()
            elif key_id == ord("q"):
                self.on_speed()
            elif key_id == ord("d"):
                if not FLAG_PLAYING:
                    self.on_next_frame()
            elif key_id == ord('a'):
                if not FLAG_PLAYING:
                    self.on_previous_frame()
            elif key_id == ord('s'):
                self.on_labeling()
                self.components_right_low[4].setDisabled(True)

    @pyqtSlot(QImage)
    def update_image(self, qImg):
        self.image_label.setPixmap(QPixmap.fromImage(qImg))


    def on_radio(self, r):
        if self.inital_completed:
            self.overlay.show()
        self.thread_update_list_radio()


    def on_play(self):
        self.components_right_low[0].setFocus()
        global FLAG_PLAYING
        FLAG_PLAYING = not FLAG_PLAYING

        if FLAG_PLAYING:
            self.components_right_low[0].setText("Pulse(space)")
            self.thread_play_video()
            self.components_right_low[2].setDisabled(True)
            self.components_right_low[3].setDisabled(True)
        else:
            self.components_right_low[0].setText("Play(space)")
            self.components_right_low[2].setDisabled(False)
            self.components_right_low[3].setDisabled(False)

    def on_speed(self):
        self.components_right_low[0].setFocus()
        self.play_speed = (self.play_speed + 1) % 3
        self.components_right_low[1].setText("Speed(q): %d" % self.play_speed)

    def on_slider(self):
        global FLAG_PLAYING
        FLAG_PLAYING = False
        self.slider_queue.empty()
        if self.video_stream is not None:
            if self.slider.value() % 20 == 0 and self.slider.value() > 0:
                self.video_stream.set(cv2.CAP_PROP_POS_FRAMES, self.slider.value())
                grab, frame = self.video_stream.read()
                self.th.frames_queue.put(frame)

    def on_slider_release(self):
        self.components_right_low[0].setFocus()
        global FLAG_PLAYING
        FLAG_PLAYING = True
        self.components_right_low[0].setText("Pulse(space)")
        self.thread_play_video()


    def on_select_cage(self):
        if self.inital_completed:
            self.overlay.show()
        self.thread_get_animals()


    def on_select_animal(self):
        if self.inital_completed:
            self.overlay.show()
        self.animal = self.components_left[3].currentText()
        self.thread_get_videos()

    def on_select_date_min(self):
        if self.inital_completed:
            self.overlay.show()
        self.thread_update_list_min()

    def on_select_date_max(self):
        if self.inital_completed:
            self.overlay.show()
        self.thread_update_list_max()

    def on_select_video(self):
        global FLAG_PLAYING
        if self.inital_completed:
            self.overlay.show()
        FLAG_PLAYING = False
        self.slider_queue.empty()
        self.slider_queue.put(1)
        self.video_path = self.components_left[10].selectedItems()[0].text()
        self.thread_load_video()
        self.components_right_low[2].setDisabled(False)
        self.components_right_low[3].setDisabled(False)

    def on_next_frame(self):
        self.components_right_low[0].setFocus()
        current_pos = self.slider.value() + 1
        if current_pos >= self.total_frames - 1:
            current_pos = 0
        self.slider_queue.put(current_pos)
        self.video_stream.set(cv2.CAP_PROP_POS_FRAMES, current_pos)
        grab, frame = self.video_stream.read()
        self.th.frames_queue.put(frame)

    def on_previous_frame(self):
        self.components_right_low[0].setFocus()
        current_pos = self.slider.value() - 1
        if current_pos <= 1:
            current_pos = self.total_frames - 2
        self.slider_queue.put(current_pos)
        self.video_stream.set(cv2.CAP_PROP_POS_FRAMES, current_pos)
        grab, frame = self.video_stream.read()
        self.th.frames_queue.put(frame)



    def on_clean_all(self):
        buttonReply = QMessageBox.question(self, 'PyQt5 message', "Do you want to delete all the labels in this video?",
                                           QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Cancel)
        if buttonReply == QMessageBox.Yes:
            sql = sqlHandler(self.database_local_dir)
            sql.delete(self.video_path)
            sql.close()
            self._update_video_list()
        self.components_right_low[0].setFocus()

    def on_labeling(self):
        global FLAG_EVENT_START
        self.start_frame = self.slider.value()
        items = self.components_left[10].selectedItems()
        if len(items) > 0:
            FLAG_EVENT_START = True
        else:
            FLAG_EVENT_START = False
        self.components_right_low[4].setDisabled(True)
        self.components_right_low[0].setFocus()

    def on_saving(self, event_id):
        sql = sqlHandler(self.database_local_dir)
        global FLAG_EVENT_START
        self.end_frame = self.slider.value()
        if event_id in self.event_dict.keys():
            if event_id != 4:
                sql.insert(self.video_path, self.start_frame, self.end_frame, self.event_dict[event_id])
            FLAG_EVENT_START = False
        sql.close()
        self.components_right_low[4].setDisabled(False)

    def on_table(self):
        self.thread_get_table()
###################################################################################################################
    def thread_get_table(self):
        self.overlay.show()
        # Pass the function to execute
        worker = Worker(self._get_table)  # Any other args, kwargs are passed to the run function
        worker.signals.result.connect(self.print_output)
        worker.signals.finished.connect(self.thread_complete)
        worker.signals.progress.connect(self.progress_fn)
        # Execute
        self.threadpool.start(worker)

    def _get_table(self, progress_callback):
        time_string = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        def get_date(data_item):
            date = data_item[8]
            date_list = date.split('-')
            d = date_list[0]
            m = date_list[1]
            y = date_list[2]
            if len(y) == 2:
                y = '20' + y
            return y + "-" + m + "-" + d

        def date_string_sort(item):

            datetime_key = datetime.datetime.strptime(item, '%Y-%b-%d')
            days = (datetime_key.year - 2000) * 365 + datetime_key.month * 30 + datetime_key.day
            return days
            # datetime_key = datetime.datetime.strptime('15/Nov/2013', '%d/%b/%Y').date()
            

        F = copy.deepcopy(self.F)
        if not os.path.exists('forms'):
            os.mkdir('forms')
        for key in F.cages_dict.keys():
            file_name = os.path.join("forms", key + '_' + time_string + ".csv")
            dict_animal_date = {}


            # if "sync" not in key or not ("10" in key or "11" in key):
            #     continue
            # if "sync" not in key or not ("9" in key):
            #     continue
            print(key)
            for animal in tqdm(F.get_animals(key)):
                animal_dir = os.path.join(F.animal_dict[animal], 'Logs')
                temp_logs_list = os.listdir(animal_dir)
                if len(temp_logs_list) == 0:
                    continue
                for logs_file in temp_logs_list:
                    print(logs_file)
                    if logs_file.endswith('.csv'):
                        data = pd.read_csv(os.path.join(animal_dir, logs_file), skiprows=0, header=None)
                        num_item = data.shape[0]
                        num_class = data.shape[1]
                        dict_date = {}
                        for i in range(num_item):
                            temp_data = data.values[i]
                            if get_date(temp_data) not in dict_date.keys():
                                dict_date[get_date(temp_data)] = []
                            dict_date[get_date(temp_data)].append(temp_data)
                        for key in dict_date.keys():
                            length = len(dict_date[key])
                            processed_item = [0 for i in range(7)]
                            for i in range(length):
                                processed_item[0] += dict_date[key][i][5]
                                processed_item[1] += dict_date[key][i][6]
                                processed_item[2] += 1
                                start_time = datetime.datetime.strptime(dict_date[key][i][9], "%H:%M:%S")
                                end_time = datetime.datetime.strptime(dict_date[key][i][11], "%H:%M:%S")
                                processed_item[4] += (end_time - start_time).seconds
                                if dict_date[key][i][3] < 2:
                                    print(dict_date[key][i][3])
                                if dict_date[key][i][3] > 1:
                                    processed_item[3] += 1
                                    processed_item[5] += (end_time - start_time).seconds
                                    processed_item[6] += dict_date[key][i][3]
                            processed_item[0] = float(processed_item[0]) / float(length)
                            processed_item[1] = float(processed_item[1]) / float(length)
                            dict_date[key] = processed_item
                        dict_animal_date[animal] =dict_date
            list_key_date = []
            for key_animal in dict_animal_date.keys():
                for key_date in dict_animal_date[key_animal].keys():
                    if key_date not in list_key_date:
                        list_key_date.append(key_date)
            list_key_date.sort(key=date_string_sort)
            list_key_date.sort()
            index_list_date = []

            for i in range(7):
                for key_date in list_key_date:
                    index_list_date.append(key_date)

            index_list_attr = []
            attributes = ['Distance_FB', 'Distance_LR', 'Total Entries', 'Total Effective Entries', 'Total Time', 'Total Effective Time', 'Total Arm Raise']
            for i in range(7):
                for key_date in list_key_date:
                    index_list_attr.append(attributes[i])

            array_index = [index_list_date, index_list_attr]
            tuples = list(zip(*array_index))
            index_list = pd.MultiIndex.from_tuples(tuples, names=['first', 'second'])
            data_matrix = np.zeros((5, len(list_key_date) * 7))
            i = 0
            for key_animal in dict_animal_date.keys():
                date_list = list(dict_animal_date[key_animal].keys())
                date_list.sort(key=date_string_sort)
                for key_date in date_list:
                    start = list_key_date.index(key_date)
                    for att_index in range(7):
                        # data_matrix[i][start: start + 7] = dict_animal_date[key_animal][key_date]
                        data_matrix[i][start] = dict_animal_date[key_animal][key_date][att_index]
                        start += len(list_key_date)
                i += 1
            df = pd.DataFrame(data_matrix, index=['MOUSE1', 'MOUSE2', 'MOUSE3', 'MOUSE4', 'MOUSE5'], columns=index_list)
            df.to_csv(file_name)
            print("OK")
        return 0
###################################################################################################################
    def thread_get_cages(self):
        self.overlay.show()
        # Pass the function to execute
        worker = Worker(self._get_cages)  # Any other args, kwargs are passed to the run function
        worker.signals.result.connect(self._set_cages)
        worker.signals.finished.connect(self.thread_complete)
        worker.signals.progress.connect(self.progress_fn)
        # Execute
        self.threadpool.start(worker)

    def _get_cages(self, progress_callback):
        if self.F is None:
            self.F = FileStructure(self.root_dir)
        return self.F.get_cages()

    def _set_cages(self, cages):
        self.components_left[1].clear()
        self.components_left[3].clear()
        self.components_left[10].clear()
        for cage in cages:
            self.components_left[1].addItem(cage)
################################################################################################################
    def thread_get_animals(self):
        self.overlay.show()
        # Pass the function to execute
        worker = Worker(self._get_animals)  # Any other args, kwargs are passed to the run function
        worker.signals.result.connect(self._set_animals)
        worker.signals.finished.connect(self.thread_complete)
        worker.signals.progress.connect(self.progress_fn)
        # Execute
        self.threadpool.start(worker)

    def _get_animals(self, progress_callback):
        self.overlay.show()
        return self.F.get_animals(self.components_left[1].currentText())

    def _set_animals(self, animals):
        self.components_left[3].clear()
        self.components_left[10].clear()
        for animal in animals:
            self.components_left[3].addItem(animal)
#################################################################################################################
    def thread_get_videos(self):
        # Pass the function to execute
        self.overlay.show()
        worker = Worker(self._get_videos)  # Any other args, kwargs are passed to the run function
        worker.signals.result.connect(self._set_videos)
        worker.signals.finished.connect(self.thread_complete)
        worker.signals.progress.connect(self.progress_fn)
        # Execute
        self.threadpool.start(worker)

    def _get_videos(self, progress_callback):
        while self.animal == '':
            self.animal = self.components_left[3].currentText()
            time.sleep(0.5)
        self.F.get_video_list(self.animal)

    def _set_videos(self, animals):
        self._update_video_list()
#################################################################################################################
    def thread_load_video(self):
        self.overlay.show()
        # Pass the function to execute
        worker = Worker(self._load_video)  # Any other args, kwargs are passed to the run function
        worker.signals.result.connect(self._set_frame)
        worker.signals.finished.connect(self.thread_complete)
        worker.signals.progress.connect(self.progress_fn)
        # Execute
        self.threadpool.start(worker)

    def _load_video(self, progress_callback):
        # shutil.rmtree('temp', ignore_errors=True)
        # os.mkdir('temp')
        # shutil.copyfile(self.video_path, os.path.join('temp', os.path.basename(self.video_path)))
        if self.video_stream is not None:
            self.video_stream.release()
        # self.video_stream = cv2.VideoCapture(os.path.join('temp', os.path.basename(self.video_path)))
        self.video_stream = cv2.VideoCapture(self.video_path)
        self.total_frames = self.video_stream.get(cv2.CAP_PROP_FRAME_COUNT)
        self.slider.setRange(0, self.total_frames)
        return None

    def _set_frame(self, _):
        if not self.video_stream.isOpened():
            root = Tk()
            root.withdraw()
            messagebox.showerror("Error", "Broken video!")
            self.video_stream = None
        else:
            grab, frame = self.video_stream.read()
            self.th.frames_queue.put(frame)
            # self.th.frames_queue.put(self.preload_buffer.get())
            for i in range(len(self.components_right_low)):
                self.components_right_low[i].setDisabled(False)
            self.components_right_low[0].setFocus()
#################################################################################################################
    def thread_play_video(self):
        # Pass the function to execute
        worker = Worker(self._play_video)  # Any other args, kwargs are passed to the run function
        worker.signals.result.connect(self._close_video)
        worker.signals.finished.connect(self.thread_complete)
        worker.signals.progress.connect(self.progress_fn)
        # Execute
        self.threadpool.start(worker)

    def showdialog(self):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setText("Are you sure there is no event in this video?")
        msg.setWindowTitle("No events confirmation")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        retval = msg.exec_()
        msg.close()
        msg.destroy()
        return retval

    def _play_video(self, progress_callback):
        total_frames = self.video_stream.get(cv2.CAP_PROP_FRAME_COUNT)
        global FLAG_PLAYING

        while FLAG_PLAYING:
            current_pos = self.slider.value() + 1
            self.slider_queue.put(current_pos)
            time.sleep([0.05, 0.02, 0][self.play_speed])
            if current_pos < total_frames - 1:
                grab, frame = self.video_stream.read()
                if grab and frame is not None:
                    self.th.frames_queue.put(frame)
                # if self.preload_buffer.qsize() > 0:
                #     self.th.frames_queue.put(self.preload_buffer.get())
            else:
                FLAG_PLAYING = False
                self.components_right_low[2].setDisabled(False)
                self.components_right_low[3].setDisabled(False)
                break

    def _close_video(self, _):
        total_frames = self.video_stream.get(cv2.CAP_PROP_FRAME_COUNT)
        self.components_right_low[0].setText("Play(space)")
        if self.slider.value() >= total_frames - 2:
            sql = sqlHandler(self.database_local_dir)
            flag = sql.is_labeled(self.video_path)
            sql.close()
            buttonReply = True
            if not flag:
                buttonReply = self.showdialog()
                if buttonReply == QMessageBox.Yes:
                    sql = sqlHandler(self.database_local_dir)
                    sql.insert(self.video_path, 0, 0, 'empty')
                    sql.close()
                    buttonReply = True
                else:
                    buttonReply = False

            if (self.video_path not in self.current_video_list_labeled) and buttonReply:
                self.current_video_list_labeled.append(self.video_path)
            self.current_video_list_unlabeled = [item for item in self.current_video_list_all if
                                                 item not in self.current_video_list_labeled]
            self.components_left[10].clear()
            if self.radio_group[0].isChecked():
                if len(self.current_video_list_unlabeled) > 0:
                    self.components_left[10].addItems(self.current_video_list_unlabeled)
            elif self.radio_group[1].isChecked():
                if len(self.current_video_list_labeled) > 0:
                    self.components_left[10].addItems(self.current_video_list_labeled)

#################################################################################################################
    def thread_update_list_min(self):
        self.overlay.show()
        # Pass the function to execute
        worker = Worker(self._update_list_min)  # Any other args, kwargs are passed to the run function
        worker.signals.result.connect(self.print_output)
        worker.signals.finished.connect(self.thread_complete)
        worker.signals.progress.connect(self.progress_fn)
        # Execute
        self.threadpool.start(worker)

    def _update_list_min(self, progress_callback):
        self.components_left[10].clear()
        Q_min_date = self.components_left[6].selectedDate()
        self.min_date = datetime.datetime.strptime(
            "%d-%d-%d" % (Q_min_date.year(), Q_min_date.month(), Q_min_date.day()), "%Y-%m-%d")
        self.components_left[8].setMinimumDate(self.min_date)
        self._update_video_list()
        return "_update_list_min"
#################################################################################################################
    def thread_update_list_max(self):
        self.overlay.show()
        # Pass the function to execute
        worker = Worker(self._update_list_max)  # Any other args, kwargs are passed to the run function
        worker.signals.result.connect(self.print_output)
        worker.signals.finished.connect(self.thread_complete)
        worker.signals.progress.connect(self.progress_fn)
        # Execute
        self.threadpool.start(worker)

    def _update_list_max(self, progress_callback):
        self.components_left[10].clear()
        Q_max_date = self.components_left[8].selectedDate()
        self.max_date = datetime.datetime.strptime(
            "%d-%d-%d" % (Q_max_date.year(), Q_max_date.month(), Q_max_date.day()), "%Y-%m-%d")
        self._update_video_list()
        return "_update_list_max"
#################################################################################################################
    def thread_update_list_radio(self):
        self.overlay.show()
        # Pass the function to execute
        worker = Worker(self._update_list_radio)  # Any other args, kwargs are passed to the run function
        worker.signals.result.connect(self.print_output)
        worker.signals.finished.connect(self.thread_complete)
        worker.signals.progress.connect(self.progress_fn)
        # Execute
        self.threadpool.start(worker)

    def _update_list_radio(self, progress_callback):
        self._update_video_list()
        return "_update_list_radio"
#################################################################################################################
    def thread_update_slider(self):
        th = threading.Thread(target=self.process_slider)
        th.start()

    def process_slider(self):
        while True:
            if self.slider_queue.qsize() > 0:
                self.slider.setValue(self.slider_queue.get())
#################################################################################################################
    def thread_update_database(self):
        th = threading.Thread(target=self.update_database)
        th.start()
    def update_database(self):
        global FLAG_DATABASE_SAFE
        database_cloud_dir = os.path.join(self.root_dir, 'database')
        if not os.path.exists(database_cloud_dir):
            os.mkdir(database_cloud_dir)
        while True:
            time.sleep(60)
            if FLAG_DATABASE_SAFE:
                try:
                    shutil.copy(self.database_local_dir, os.path.join(database_cloud_dir, os.path.basename(self.database_local_dir)))
                    sys.stdout.write(
                        "\r [%s] Database synchronized into %s ..." % (str(datetime.datetime.now()), database_cloud_dir))
                    sys.stdout.flush()
                except:
                    pass
            else:
                print("Database Not Safe! Will try next time...")
#################################################################################################################
    def thread_preload_video(self):
        th = threading.Thread(target=self.preload_video)
        th.start()

    def preload_video(self):
        while True:
            if self.video_stream is not None:
                if self.preload_buffer.qsize() < self.preload_size:
                    try:
                        if self.slider.value() < self.video_stream.get(cv2.CAP_PROP_FRAME_COUNT) - 2:
                            grab, frame = self.video_stream.read()
                            self.preload_buffer.put(frame)
                    except:
                        grab = False
                        while not grab:
                            self.video_stream.release()
                            self.video_stream = cv2.VideoCapture(self.video_path)
                            self.video_stream.set(cv2.CAP_PROP_POS_FRAMES, self.slider.value())
                            grab, frame = self.video_stream.read()
                            self.preload_buffer.put(frame)

#################################################################################################################
    def _update_video_list(self):
        animal = self.components_left[3].currentText()
        filtered_items = self.F.get_filtered_video_list(animal, self.min_date, self.max_date)
        sql = sqlHandler(self.database_local_dir)
        self.current_video_list_all = filtered_items
        self.current_video_list_labeled = [item for item in self.current_video_list_all if sql.is_labeled(item)]
        self.current_video_list_unlabeled = [item for item in self.current_video_list_all if
                                             item not in self.current_video_list_labeled]
        sql.close()
        self.components_left[10].clear()
        if self.radio_group[0].isChecked():
            if len(self.current_video_list_unlabeled) > 0:
                self.components_left[10].addItems(self.current_video_list_unlabeled)
        elif self.radio_group[1].isChecked():
            if len(self.current_video_list_labeled) > 0:
                self.components_left[10].addItems(self.current_video_list_labeled)

    def progress_fn(self, n):
        pass

    def print_output(self, s):
        pass

    def thread_complete(self, s):
        global FLAG_COMPLETE
        FLAG_COMPLETE = True
        if s:
            print("Thread complete: %s" % s)

    def resizeEvent(self, event):
        self.overlay.resize(event.size())
        event.accept()

class tableDialog(QDialog):

    def __init__(self, parent, FileStructure):
        super(tableDialog, self).__init__(parent)
        self.setWindowTitle("Generate table")
        self.button_generate = QPushButton("Generate", self)
        self.button_generate.move(110, 80)

        self.radio_button_1 = QRadioButton('Option 1', self)
        self.radio_button_2 = QRadioButton('Option 2', self)
        self.radio_button_3 = QRadioButton('Option 3', self)
        self.radio_button_1.move(20, 50)
        self.radio_button_2.move(120, 50)
        self.radio_button_3.move(220, 50)
        self.radio_button_group_1 = QButtonGroup()
        self.radio_button_group_1.addButton(self.radio_button_1)
        self.radio_button_group_2 = QButtonGroup()
        self.radio_button_group_2.addButton(self.radio_button_2)
        self.radio_button_group_3 = QButtonGroup()
        self.radio_button_group_3.addButton(self.radio_button_3)
        self.button_generate.clicked.connect(self.on_generate)

        self.F = copy.deepcopy(FileStructure)

    def on_generate(self):

        self.exec_()
        self.close()
        self.destroy()

    def __generate_table(self):
        pass
if __name__ == '__main__':
    app = QApplication([])
    start_window = StartWindow()
    start_window.show()
    app.exit(app.exec_())
