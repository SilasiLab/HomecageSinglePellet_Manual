import os
import datetime
import sqlite3

class sqlHandler(object):

    def __init__(self, database_name='database/homecage_database.sqlite', safe_flag=True):
        self.safe_flag = safe_flag
        if self.safe_flag:
            global FLAG_DATABASE_SAFE
            FLAG_DATABASE_SAFE = False
        self.conn = sqlite3.connect(database_name)
        self.cursor = self.conn.cursor()
        if len(self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()) <= 0:
            self.create_table()

    def insert(self, video_path, start_frame, end_frame, event_type):
        video_name = os.path.basename(video_path)
        video_dir = os.path.dirname(video_path)
        time_stamp = datetime.datetime.strptime(video_name.split(')_')[0], '%Y-%m-%d_(%H-%M-%S')
        animal = int(video_dir.split(os.path.sep)[-2].replace('MOUSE', ''))
        cage = video_dir.split(os.path.sep)[-4]
        try:
            self.cursor.execute('''INSERT INTO EVENT
                                (CAGE,ANIMAL,TIMESTAMP,VIDEO_PATH,START_FRAME,END_FRAME,EVENT_TYPE)
                                VALUES ('%s',%d,'%s','%s',%d,%d,'%s')''' %
                                (cage, animal, time_stamp, video_path, start_frame, end_frame, event_type))
            self.conn.commit()
        except:
            print("Connection error")

    def delete(self, video_path):
        if self.is_labeled(video_path):
            self.cursor.execute('''
            DELETE from EVENT where VIDEO_PATH = '%s'
            ''' % video_path)
            self.conn.commit()

    def is_labeled(self, video_path):
        self.cursor.execute("SELECT * FROM EVENT WHERE VIDEO_PATH == '%s'" % video_path)
        if len(self.cursor.fetchall()) > 0:
            return True
        else:
            return False

    def create_table(self):
        self.cursor.execute('''CREATE TABLE EVENT
                 (ID INTEGER PRIMARY KEY     NOT NULL,
                 CAGE           VARCHAR    NOT NULL,
                 ANIMAL            INT     NOT NULL,
                 TIMESTAMP        SMALLDATETIME,
                 VIDEO_PATH          VARCHAR,
                 START_FRAME          INT,
                 END_FRAME          INT,
                 EVENT_TYPE          VARCHAR
                 );''')

    def close(self):
        self.conn.close()
        if self.safe_flag:
            global FLAG_DATABASE_SAFE
            FLAG_DATABASE_SAFE = True

    def open(self):
        return self.__init__()


class FileStructure:
    def __init__(self, root_dir):
        """
        Construct the tree structure for searching files.
        :param root_dir: A directory string, Homecages folders should be under this directory.
        """
        self.root_dir = root_dir
        self.cages_dir = [os.path.join(self.root_dir, item) for item in os.listdir(self.root_dir)
                          if 'homecage' in item.lower()]

        self.mice_dir = []
        cages_dir_list = []

        for cage in self.cages_dir:
            animal_dir = os.path.join(cage, 'AnimalProfiles')
            if os.path.exists(animal_dir):
                cage_list = os.listdir(os.path.join(cage, 'AnimalProfiles'))
                if len(cage_list) > 0:
                    self.mice_dir.extend([os.path.join(cage, item) for item in cage_list
                                          if 'test' not in item.lower()])
                    cages_dir_list.append(cage)
                else:
                    self.cages_dir.remove(cage)

        self.cages_dir = cages_dir_list
        self.cages_dict = {}

    def get_cages(self):
        for item in self.cages_dir:
            self.cages_dict[os.path.basename(item)] = item
        return list(self.cages_dict.keys())

    def get_animals(self, cage):
        self.animal_dict = {}
        self.video_list = []
        self.filtered_video_list = []
        try:
            animal_dir = os.path.join(self.cages_dict[cage], 'AnimalProfiles')
        except Exception as e:
            print(e)
            return []
        animal_list = [item for item in os.listdir(animal_dir) if "test" not in item.lower()]
        for animal in animal_list:
            self.animal_dict[animal] = os.path.join(animal_dir, animal)
        return animal_list

    def get_video_list(self, animal):
        self.filtered_video_list = []
        if len(self.video_list) > 0:
            return self.video_list
        else:
            animal_dir = os.path.join(self.animal_dict[animal], "")
            animal_dir = [os.path.join(animal_dir, item) for item in os.listdir(animal_dir) if "video" in item.lower()][
                0]
            self.video_list = [os.path.join(animal_dir, item) for item in os.listdir(animal_dir) if
                               item.endswith(".avi")]
        return self.video_list

    def get_filtered_video_list(self, animal, min_date, max_date):
        def get_date(video_file_path):
            date = os.path.basename(video_file_path).split('_')[0]
            try:
                date = datetime.datetime.strptime(date, "%Y-%m-%d")
            except:
                date = None
            return date

        for video_path in self.get_video_list(animal):
            if get_date(video_path) != None:
                if get_date(video_path) >= min_date and get_date(video_path) <= max_date:
                        self.filtered_video_list.append(video_path)
        return self.filtered_video_list


if __name__ == '__main__':
    root_dir = "/mnt/googleDrive"
    F = FileStructure(root_dir)
