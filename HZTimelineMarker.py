import json
from maya import mel
from maya import cmds
from maya.api import OpenMaya
from PySide2 import QtWidgets, QtGui, QtCore
import shiboken2
from maya import OpenMayaUI


TIMELINE_MARKER = "timeline-marker"


def maya_to_qt(name, type_=QtWidgets.QWidget):
    """
    :param str name: Maya path of an ui object
    :param cls type_:
    :return: QWidget of parsed Maya path
    :rtype: QWidget
    :raise RuntimeError: When no handle could be obtained
    """
    ptr = OpenMayaUI.MQtUtil.findControl(name)
    if ptr is None:
        ptr = OpenMayaUI.MQtUtil.findLayout(name)
    if ptr is None:
        ptr = OpenMayaUI.MQtUtil.findMenuItem(name)
    if ptr is not None:
        ptr = int(ptr)
        return shiboken2.wrapInstance(ptr, type_)

    raise RuntimeError("Failed to obtain a handle to '{}'.".format(name))

        
# ----------------------------------------------------------------------------


def get_timeline_path():
    """
    :return: Object path of Maya's timeline
    :rtype: str
    """
    return mel.eval("$tmpVar=$gPlayBackSlider")

    
def get_timeline():
    """
    Get the QWidget of Maya's timeline. For versions 2016.5 and later the 
    first QWidget child of the timeline should be returned.
    
    :return: QWidget of Maya's timeline
    :rtype: QtWidgets.QWidget
    """
    # convert name to widget
    timeline_path = get_timeline_path()
    timeline = maya_to_qt(timeline_path)
    
    # return child for Maya 2016.5 > 
    for child in timeline.children():
        if isinstance(child, QtWidgets.QWidget):
            return child
    
    return timeline

      
def get_timeline_range():
    """
    :return: Frame range of timeline selection
    :rtype: list[int]
    """
    timeline_path = get_timeline_path()
    timeline_range = cmds.timeControl(timeline_path, query=True, rangeArray=True)
    return range(int(timeline_range[0]), int(timeline_range[1]))

    
# ----------------------------------------------------------------------------


def remap(value, input_min, input_max, output_min, output_max):
    """
    Remap a value based on input minimum and maximum, the result is converted
    to an integer since markers can only live as a whole frame.
    
    :param float value: Value to remap
    :param float input_min: Original minimum
    :param float input_max: Original maximum
    :param float output_min: New minimum
    :param float output_max: New maximum
    :return: Remapped value
    :rtype: int
    """
    return (((value - input_min) * (output_max - output_min)) / (input_max - input_min)) + output_min



class HZTimelineMark(object):
    """
    The time line mark class contains the colour and comment. Due to the mark
    sometimes being added for unknown reason an enabled state has been added
    to ensure default initialization doesn't cause the mark to be drawn.
    """
    slots = ("colour", "comment", )

    def __init__(self, colour=(0, 255, 0), comment=""):
        self.colour = colour
        self.comment = comment


class HZTimelineMarker(QtWidgets.QWidget):
    """
    Unable to subclass the __new__ method in certain versions of PySide2,
    we manage the instance ourselves but unable to make a true singleton.
    """
    instance = None

    def __init__(self, parent):
        super(HZTimelineMarker, self).__init__(parent)

        self.setObjectName('HZTimelineMarkerWidget')

        # variables
        self.start = None
        self.end = None
        self.total = None
        self.step = None

        self.data = {}
        self.range = None
        self.callbacks = []

        # initialize
        self.load_from_scene()
        self.register_callbacks()

        self.installEventFilter(self)

    @classmethod
    def get_instance(cls):
        if cls.instance is None:
            raise RuntimeError("not initilized")
        return cls.instance 

     # ------------------------------------------------------------------------

    def paintEvent(self, event):
        """
        When the paint event is called draw all of the timeline markes onto
        the widget.

        :param QtCore.QEvent event:
        :return: Event state
        :rtype: bool
        """
        # print ('paintEvent => ', self, event)
        if not isinstance(self, HZTimelineMarker): return False
            # if not issubclass(type(self), HZTimelineMarker): return False


        # get animation range
        self.start = cmds.playbackOptions(query=True, minTime=True)
        self.end = cmds.playbackOptions(query=True, maxTime=True)

        # calculate frame width
        self.total = self.width()
        self.step = (self.total - (self.total * 0.01)) / (self.end - self.start + 1)

        # validate marker information
        if not self.data:
            return

        # setup painter and pen
        painter = QtGui.QPainter(self)
        pen = QtGui.QPen()
        pen.setWidth(self.step)

        # draw lines for each frame
        for frame, frame_data in self.data.items():
            if not self.start <= frame <= self.end:
                continue

            r, g, b = frame_data.colour
            pen.setColor(QtGui.QColor(r, g, b, 50))

            pos = (frame - self.start + 0.5) * self.step + (self.total * 0.005)
            line = QtCore.QLineF(QtCore.QPointF(pos, 0), QtCore.QPointF(pos, 100))

            painter.setPen(pen)
            painter.drawLine(line)

        return super(HZTimelineMarker, self).paintEvent(event)

    def eventFilter(self, obj, event):
        if isinstance(obj, HZTimelineMarker):
            if event.type() in [QtCore.QEvent.ToolTip]: 
                QtWidgets.QToolTip.hideText()
                frame = int(((event.x() - (self.total * 0.005)) / self.step) + self.start)
                frame_data = self.data.get(frame)
                if frame_data is not None:
                    QtWidgets.QToolTip.showText(event.globalPos(), frame_data.comment, self)
                return True

        return False # super(HZTimelineMarker, self).eventFilter(obj, event)

    # ------------------------------------------------------------------------

    def update(self):
        """
        Subclass update to simultaneously store all of the marker data into
        the current scene.
        """
        self.write_to_scene()
        super(HZTimelineMarker, self).update()
        
    def deleteLater(self):
        """
        Subclass the deleteLater function to first remove the callback, 
        this callback shouldn't be floating around and should be deleted
        with the widget.
        """

        self.remove_callbacks()
        super(HZTimelineMarker, self).deleteLater()

    # ------------------------------------------------------------------------

    def press_command_callback(self, *args):
        """
        Press callback on the timeline, this callback registers the current
        selected frames, if the user settings determine that the frame range
        is not important ( no automated shifting of markers ), no range will
        be stored.
        """
        timeline_path = get_timeline_path()
        cmds.timeControl(timeline_path, edit=True, beginScrub=True)

        # check if range needs to be stored
        range_visible = cmds.timeControl(timeline_path, query=True, rangeVisible=True)
        if range_visible:
            self.range = get_timeline_range()
        else:
            self.range = None

    def release_command_callback(self, *args):
        """
        Release callback on the timeline, together with the press command the
        difference can be extracted and the markers can be moved accordingly.
        Theuser settings will be checked if the moving of markers is
        appropriate.
        """
        timeline_path = get_timeline_path()
        cmds.timeControl(timeline_path, edit=True, endScrub=True)

        # check if markers need to be shifted
        if not self.range:
            return

        # get begin and end range
        start_range = self.range[:]
        end_range = get_timeline_range()

        # reset stored range
        self.range = None

        # check data
        start_length = len(start_range)
        end_length = len(end_range)
        range_visible = cmds.timeControl(timeline_path, query=True, rangeVisible=True)
        if (start_length == 1 and end_length != 1) or not range_visible:
            return

        # remap frames
        matches = {frame: self.data[frame] for frame in start_range if frame in self.data}
        for frame, frame_data in matches.items():
            if start_length == 1:
                frame_remapped = end_range[0]
            else:
                frame_remapped = int(
                    remap(
                        frame,
                        input_min=start_range[0],
                        input_max=start_range[-1],
                        output_min=end_range[0],
                        output_max=end_range[-1]
                    )
                )

            # continue if frame is the same
            if frame == frame_remapped:
                continue

            # update data
            self.data[frame_remapped] = frame_data
            self.data.pop(frame, None)

        self.update()

    # ------------------------------------------------------------------------

    @classmethod
    def add(cls, frame, colour, comment):
        """
        Add a marker based on the provided arguments. If the frames are
        already marked this information will be overwritten.

        :param int frame:
        :param list[int] colour:
        :param str comment:
        """
        instance = cls.get_instance()
        instance.data[frame] = HZTimelineMark(colour, comment)
        instance.update()

    @classmethod
    def set(cls, frames, colours, comments):
        """
        :param list frames:
        :param list colours:
        :param list comments:
        """
        instance = cls.get_instance()
        instance.data.clear()
        for frame, colour, comment in zip(frames, colours, comments):
            instance.data[frame] = HZTimelineMark(colour, comment)
        instance.update()

    @classmethod
    def remove(cls, *frames):
        """
        :param int frames: Frame number
        """
        instance = cls.get_instance()
        for frame in frames:
            instance.data.pop(frame, None)
        instance.update()

    @classmethod
    def clear(cls):
        """
        Remove all markers.
        """
        instance = cls.get_instance()
        instance.data.clear()
        instance.update()

    # ------------------------------------------------------------------------

    def register_callbacks(self):
        """
        Register a callback to run the read function every time a new scene is
        initialized or opened.
        """
        self.callbacks = [
            OpenMaya.MSceneMessage.addCallback(OpenMaya.MSceneMessage.kAfterNew, self.load_from_scene),
            OpenMaya.MSceneMessage.addCallback(OpenMaya.MSceneMessage.kAfterOpen, self.load_from_scene)
        ]

        timeline_path = get_timeline_path()
        cmds.timeControl(
            timeline_path,
            edit=True,
            pressCommand=self.press_command_callback,
            releaseCommand=self.release_command_callback,
        )

    def remove_callbacks(self):
        """
        Remove the callbacks that update the time line markers every time a
        new scene is initialized or opened.
        """
        if self.callbacks:
            OpenMaya.MMessage.removeCallbacks(self.callbacks)

        timeline_path = get_timeline_path()
        cmds.timeControl(timeline_path, edit=True, pressCommand=None, releaseCommand=None)

    # ------------------------------------------------------------------------

    def load_from_scene(self, *args):
        """
        Marker data can be stored in the Maya's scenes themselves, the
        fileInfo command is used for this and the data is stored under the
        "timeline-marker" argument. This data can be decoded with json and
        split it the frames, colours and comments, as the format has changed
        slightly loading is made backwards compatible with older versions of
        the tool.
        """
        # clear existing data
        self.data.clear()

        # get data
        data = cmds.fileInfo(TIMELINE_MARKER, query=True)
        data = json.loads(data[0].replace('\\"', '"')) if data else {}
        for frame, frame_data in data.items():
            self.data[int(frame)] = HZTimelineMark(**frame_data)

        self.update()

    def write_to_scene(self):
        """
        Get all the marker information ( frames, comments and colors ) and
        store this with the fileInfo command in the maya file. Data is
        stored under the "timelineMarker" argument.
        """
        encoded = json.dumps({frame: frame_data.__dict__ for frame, frame_data in self.data.items()})
        cmds.fileInfo(TIMELINE_MARKER, encoded)

    @staticmethod
    def masterReload():
        import sys
        #packages = ['package.to.reload','another.package.to.reload']
        for i in sys.modules.keys()[:]:
            #print(i)
            #for pkg in packages:
            if i.startswith('HZTimelineMarker'):
                del(sys.modules[i])


# global HZTimelineMarkerGlobal
# parent = get_timeline()
# layout = parent.layout()
# # create layout if non exists
# if layout is None:
#     layout = QtWidgets.QVBoxLayout(parent)
#     layout.setContentsMargins(0, 0, 0, 0)
#     parent.setLayout(layout)
# # create timeline marker
# HZTimelineMarkerGlobal = HZTimelineMarker(parent)
# if layout.count() < 1:
#     layout.addWidget(HZTimelineMarkerGlobal)

