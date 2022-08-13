# creation date : 2 June, 2022
#
# Author :    Hamed Zandieh
# Email :   hamed.zandieh@gmail.com
#
# Description :
#    This script create shot from sceneList (an excel file that presents the shots and their lenghts)
#    Also in other Tab script export multiple files of shots that created by First Tab
#    in third Tab there is some custom script that related to previuos tabs
# How To use :
#    copy python file into maya script folder then run these lines:
# import HZShotManager as hzsm
# hzsm.HZShotManager().showUI()
# 

import traceback

from maya import cmds as MC, mel as MM, utils as UT
from itertools import cycle, islice, chain
import re, json, os, subprocess, sys

class HZShotManager:

    __version__ = '2.1.0'

    def __init__(self, *args):
        self.__WINDOW_NAME = "HZShotManagerWindow"
        self.__shotsInfoKey = 'HZShotsInfoJson'
        self.__bookmarkColors = ["ff4000","ffbf00","40ff00","00bfff","0040ff","4000ff","bf00ff","ff0040"] 
    
    @staticmethod
    def loadPlugin(plugin):
        loaded = MC.pluginInfo(plugin, q=True, loaded=True)
        registered = MC.pluginInfo(plugin, q=True, registered=True)
        if not registered or not loaded:
            MC.loadPlugin(plugin)
        return plugin in MC.pluginInfo(query=True, listPlugins=True)

    @staticmethod
    def hex2rgb(hex = str):
        if not hex: return [0,0,0]
        hex = hex.upper().split("#")[-1]
        lh = len(hex)
        if lh==3:  hex = iter(''.join([str(x) * 2 for x in hex]))
        elif lh<3: 
            from itertools import cycle, islice
            hex = iter(''.join(list(islice(cycle(hex), 6))))
        else: hex = iter(hex.ljust(6,'F')[:6])
        return [round(float(int("%s%s"%(a,b),16))/255, 2) for a,b in zip(hex,hex)]   

    @staticmethod
    def getImagePath(imageName, ext="png", imageFolder="."):
        import os
        # print ("file:", __file__)
        imageFile       = "%s.%s"%(imageName, ext)
        imgPath         = os.path.join(os.path.dirname(__file__),imageFolder, imageFile)
        return imgPath

    class HZCRow:
        def __init__(self, parnt, colnum, customWidths = [], **kwargs):
            self.parnt = parnt
            self.colnum = len(customWidths) if customWidths else colnum
            self.cwidths = customWidths
            self.kwargs = kwargs
            if 'adjustableColumn' not in self.kwargs: self.kwargs.update({'adjustableColumn': 2})

        def __enter__(self):
            if not self.cwidths:
                colwid = [(i+1, int(MC.layout(self.parnt,q=1,w=1)/self.colnum)) for i in range(self.colnum)]
            else:
                colwid = [(i+1, self.cwidths[i]) for i in range(self.colnum)]
            colatc = [(i+1, 'left', 5) for i in range(self.colnum)]
            row = MC.rowLayout( parent=self.parnt, numberOfColumns=self.colnum, columnWidth=colwid,
                            columnAlign=(1, 'left'), columnAttach=colatc , **self.kwargs)

        def __exit__(self, *args):
            MC.setParent( u=1 ) 

    def saveData(self, dataDic):
        encoded = json.dumps(dataDic, ensure_ascii=True)
        MC.fileInfo(self.__shotsInfoKey, encoded)

    def loadData(self):
        data = MC.fileInfo(self.__shotsInfoKey, query=True)
        return json.loads(data[0].replace('\\"', '"')) if data else {}

    def checkProgressEscape(self):
        # check if dialog has been cancelled
        cancelled = MC.progressWindow(query=True, isCancelled=True)
        if cancelled:
            MC.progressWindow(endProgress=1)
        return cancelled 

    def setKeyShots(self,animCurves = None, shotsInfo =None, tit="Set Keyframe"):
        MC.progressWindow(title=tit , progress=0, status='proceed: 0%', isInterruptable=True)        
        if not shotsInfo: shotsInfo =  self.loadData()
        if not animCurves:
            animCurves = MC.ls(sl=1, type=['animCurveTL','animCurveTA','animCurveTU']) \
                            or MC.ls(type=['animCurveTL','animCurveTA','animCurveTU']) or []
        if not animCurves: 
            MC.warning("NO Animation Key Found!")
            return
        shotCount = len(shotsInfo)
        for idx, sh in enumerate(shotsInfo): # HOLD POSes ON SHOTS CHANGE
            if self.checkProgressEscape(): return
            MC.setKeyframe(t=[sh['start'], sh['stop']], shape=0, ott='linear', itt='linear', *animCurves) 
            amount = 100 / shotCount * float(idx)
            MC.progressWindow(edit=True, progress=amount, status='proceed: %d%%' % amount)                
            UT.processIdleEvents()  
        MC.progressWindow(endProgress=1)

    def getNestedRefs(self):
        try:
            all_reference_nodes = MC.ls(rf=True)
            all_reference_nodes.sort(key=len, reverse=False)
            nested_refs = list()
            for reference_node in all_reference_nodes:
                children = MC.referenceQuery(reference_node, referenceNode=True, child=True)
                # print (reference_node, "--->", children)
                if children: nested_refs.append(reference_node)
        except Exception: pass
        return ','.join(nested_refs) if nested_refs else ""

    @staticmethod
    def get_clipboard_text():
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32 = ctypes.windll.user32
        user32.GetClipboardData.restype = ctypes.c_void_p 
        user32.OpenClipboard(0)
        try:
            if user32.IsClipboardFormatAvailable(1):
                data = user32.GetClipboardData(1)
                #user32.SetClipboardText(c) or user32.EmptyClipboard()
                data_locked = kernel32.GlobalLock(data)
                text = ctypes.c_char_p(data_locked)
                value = text.value
                kernel32.GlobalUnlock(data_locked)
                return value
        finally:
            user32.CloseClipboard()

    def extractNumbers(self, tex):
        tex = tex.replace('.0 ', ' ')
        return [int(f) for f in re.findall("\s\d\d\d?\s", tex)]

    def generateTimeMarks(self, shotsInfo=None):
        if not shotsInfo:
            shotsInfo = self.loadData()
        if not shotsInfo:
            MC.warning("no shots info found!")
            return False
        if int(MC.about(version=True))>=2020:
            if MC.ls(typ='timeSliderBookmark'):
                MC.delete(MC.ls(typ='timeSliderBookmark'))
            if self.loadPlugin('timeSliderBookmark'):
                from maya.plugin.timeSliderBookmark.timeSliderBookmark import createBookmark # type: ignore 
                for sh in shotsInfo: createBookmark(**sh)
        else:
            sys.path.append(".")
            from PySide2 import QtWidgets
            import HZTimelineMarker as tm
            reload(tm) # type: ignore

            parent = tm.get_timeline()
            layout = parent.layout()
            # create layout if non exists
            if layout is None:
                layout = QtWidgets.QVBoxLayout(parent)
                layout.setContentsMargins(0, 0, 0, 0)
                parent.setLayout(layout)
            # create timeline marker
            tm.HZTimelineMarker.instance = tm.HZTimelineMarker(parent)
            if layout.count() < 1:
                layout.addWidget(tm.HZTimelineMarker.instance)

            tm.HZTimelineMarker.clear()
            frames = []
            cols = []
            coments = []
            for sh in shotsInfo:
                frames.extend([i for i in range(sh['start'], sh['stop'])])
                lenght = abs(sh['stop'] - sh['start']) 
                cols.extend([tuple([255*x for x in sh['color']])] * lenght)
                coments.extend([sh['name']] * lenght)
            tm.HZTimelineMarker.set(frames, cols, coments)

    def setupAnimCam(self, cam=None):
        if not cam:
            cam = MC.ls(sl=1)
        if not cam:
            MC.warning('choose camera candidate object')
            return
        if isinstance(cam, (list,tuple)): cam = cam[0]
        camShape = MC.listRelatives(cam, shapes=True)[0]
        if MC.nodeType( camShape ) != 'camera':
            MC.warning('selected object is not a camera!')
            return
        if not MC.attributeQuery('FL', ex=True, n=cam):
            MC.addAttr(cam, longName='FL', dv=35.0, k=True)
            MC.connectAttr('%s.FL'%cam, '%s.fl'%camShape)
        if not MC.attributeQuery('HZTickColor', ex=True, n=cam):
            MC.addAttr(cam, longName='HZTickColor',attributeType='bool', dv=1, k=True, hidden=True)
            MC.setKeyframe('%s.HZTickColor'%cam, time=(-50000,), insert=False)
            animCrv = MC.listConnections('%s.HZTickColor'%cam , type='animCurve')[0]
            MC.connectAttr('%s.HZTickColor'%cam, "%s.useCurveColor"%animCrv)
            MC.setAttr("%s.curveColor"%animCrv, *self.hex2rgb('bfff00'), type='double3') 
            MC.mute( '%s.HZTickColor'%cam )
        MC.viewClipPlane( camShape,fcp=100000, ncp=1.0 )
        MC.setAttr('%s.locatorScale'%camShape, 20)
        MC.setAttr('%s.filmFit'%camShape, 1)
        MC.setAttr('%s.displayResolution'%camShape, 1)
        MC.setAttr('%s.displayGateMaskColor'%camShape, 0,0,0, type='double3')
        MC.setAttr('%s.displaySafeAction'%camShape, 1)
        MC.setAttr('%s.overscan'%camShape, 1)
        MC.setAttr('%s.displayGateMaskOpacity'%camShape, 1)
        try:
            MC.setAttr('%s.sx'%cam, k=False, cb=False)
            MC.setAttr('%s.sy'%cam, k=False, cb=False)
            MC.setAttr('%s.sz'%cam, k=False, cb=False)
            MC.setAttr('%s.v'%cam, k=False, cb=True)
        except Exception: pass
        cmaSetName = 'Cam_Anim'
        if cmaSetName not in MC.listSets(allSets=1):
            MC.sets([cam], name=cmaSetName)
        else:
            MC.sets(e=1, cl=cmaSetName)
            MC.sets([cam], e=1, add=cmaSetName)
        return cam

    def showAbout(self, *args):
        import webbrowser
        DONATE_URL = "#"
        SITE_URL = "#"
        form = MC.setParent(q=True)
        MC.formLayout(form, edit=True, w=430)
        title = MC.text(label="HashZee Shot Manager - Version %s" % self.__version__, font="boldLabelFont")
        more = MC.text(label="More info:")
        site = MC.text( label="<a href=\"%s\">HashZee Shot Manager website</a>" % SITE_URL, hyperlink=True, font='boldLabelFont')
        author = MC.text(label="Author: Hamed Zandieh")
        email = MC.text(
            label="<a href=\"mailto:hamed.zandieh@gmail.com\">hamed.zandieh@gmail.com</a>", hyperlink=True, font='boldLabelFont')
        linkedin = MC.text(
            label="<a href=\"https://linkedin.com/in/hamedzandieh\">Linkedin Profile</a>", hyperlink=True, font='boldLabelFont')            
        q1 = MC.text(label="Do you like HashZee Shot Manager?", w=210)
        img = MC.iconTextButton(label="Buy Me a Coffee!", style="iconOnly", command=lambda *args: webbrowser.open_new_tab(DONATE_URL),
                                   image=self.getImagePath("jaxx-etherium-qr-code"), highlightImage=self.getImagePath("jaxx-etherium-qr-code"),
                                   )
        elt = MC.text(label="I really appreciate\nthe support!")
        MC.formLayout( form, edit=True, attachForm=[(title, 'top', 10), (title, 'left', 10), 
                                                    (more, 'top', 40), (more, 'left', 10),
                                                    (site, 'top', 55), (site, 'left', 35),
                                                    (author, 'top', 85), (author, 'left', 10),
                                                    (email, 'top', 100), (email, 'left', 35),
                                                    (linkedin, 'top', 125), (linkedin, 'left', 35),
                                                    (q1, 'top', 50),  (q1, 'left', 210),
                                                    (img, 'top', 70), (img, 'left', 210), 
                                                    (elt, 'top', 150), (elt, 'left', 30)
                                                    ] ,
                                                    attachPosition=[(img, 'right', 10, 100), (img, 'bottom', 10, 100)]
                                                    , h=200,w=430)

    def createShots(self, *args):
        try:
            MC.undoInfo(openChunk=True)
            MC.refresh(su=True)
            MC.currentUnit(time='pal')
            animCam = MC.nameField(self.objsName, q=1, object=1)
            if not animCam: 
                MC.warning("select camera")
                return
            animCam = self.setupAnimCam(animCam)
            excelcopypaste = MC.scrollField(self.excelPaste,q=1, text=1)
            frameLens = self.extractNumbers(excelcopypaste)
            if not frameLens:
                MC.warning("no frame lenghts found!")
                return
            startOffset = MC.intField(self.frmOfset, q=1, value=1) or 0
            startShotNum = MC.intField(self.shotNum, q=1, value=1) or 1
            frames = [(startOffset+1, startOffset+frameLens[0])]
            for i in range(1,len(frameLens)):
                frames.append((frames[i-1][1]+1, frames[i-1][1]+frameLens[i]))
            extendedFrames = list(chain.from_iterable(frames))
            # print (extendedFrames)
            MC.setKeyframe(animCam, t=extendedFrames, at=['translate','rotate','HZTickColor','FL'], shape=0, ott='linear', itt='linear')
            colors = list(islice(cycle(self.__bookmarkColors), len(frames)))
            shotsInfo = list()
            for idx,se in enumerate(frames):
                nm = "SH0T_%03d" % ((idx+startShotNum)*10,)
                col = self.hex2rgb(colors[idx])
                shotsInfo.append({'name':nm, 'start':se[0], 'stop':se[1], 'color':col})

            self.saveData(shotsInfo)

            self.generateTimeMarks(shotsInfo)

            MC.playbackOptions(animationStartTime=min(extendedFrames))
            MC.playbackOptions(animationEndTime=max(extendedFrames))                
            MC.playbackOptions(minTime=min(extendedFrames))
            MC.playbackOptions(maxTime=max(extendedFrames))
            MC.currentTime(extendedFrames[0]) 
            MC.select(animCam, r=1) 

            if MC.window(self.__WINDOW_NAME, exists = True): MC.deleteUI(self.__WINDOW_NAME)       

        except Exception as e:
            raise e
        finally:
            MC.refresh(su=False)
            MC.undoInfo(closeChunk=True)   

    def exportShots(self, *args):
        try:
            MC.select(cl=1)
            currentFileName = MC.file(query=True, l=True)[0]
            nestedRefTxt = self.getNestedRefs()
            # print(nestedRefTxt)
            MC.file( rename=currentFileName.replace(".ma", "_BACKUP.ma") )
            MC.file(force=True, save=True, options="v=0;", type="mayaAscii") 
            MC.file(rename= currentFileName)
            MC.file(force=True, save=True, options="v=0;", type="mayaAscii") 
            UT.processIdleEvents()
            MC.refresh(su=True)
            mayaPath = os.path.join(os.path.split(sys.executable)[0], 'mayapy.exe')
            current_project = MC.workspace(q=True, rootDirectory=True)
            scene_path, scene_name = os.path.split(currentFileName) 
            batchScriptPath = os.path.join(os.path.dirname(__file__), 'HZShotExporterCleanFilesBatch.py')    

            startOffset = MC.intField(self.expoOfset, q=1, value=1) or 0
            if not MC.fileInfo(self.__shotsInfoKey, q=1):
                MC.warning("Current scene seems has not correct config for exporting shots. no camera shots info found!")
                return
            
            shotsInfo =  self.loadData()
            allanimCurvesinScene = MC.ls(type=['animCurveTL','animCurveTA','animCurveTU'])
            setkeys, makeshotfiles, makeclean = MC.checkBoxGrp(self.chk_steps, q=1, va3=1) or [False]*3

            if setkeys:
                self.setKeyShots(allanimCurvesinScene , shotsInfo, 'Set Keyframes...')

            if makeshotfiles:
                MC.progressWindow(title='Make Shot Files' , progress=0, status='proceed: 0%', isInterruptable=True)
                shotFiles = list()
                shotsDir = os.path.join(scene_path, "SHOTS")
                if not os.path.isdir(shotsDir): os.mkdir(shotsDir)        
                shotCount = len(shotsInfo)
                dooffset = MC.intField(self.expoOfset, q=1, en=1)
                
                for idx, sh in enumerate(shotsInfo):
                    if self.checkProgressEscape(): return
                    flShInfo = []
                    if dooffset:
                        timechng = 0
                        if idx==0: timechng = startOffset+1-sh['start']
                        else: timechng = (shotsInfo[idx-1]['start']-shotsInfo[idx-1]['stop'])-1 #startOffset+1-sh['start']
                        MC.keyframe(e=1, time=(), relative=1, timeChange=timechng, *allanimCurvesinScene)
                        newStop = startOffset+1+(sh['stop']-sh['start'])
                        MM.eval('playbackOptions -min {0} -max {1} -ast {0} -aet {1}'.format(startOffset+1,newStop) )
                        flShInfo = [{'name':sh['name'], 'color':sh['color'], 'start':startOffset+1, 'stop':newStop}]
                    else:
                        MM.eval('playbackOptions -min {0} -max {1} -ast {0} -aet {1}'.format(sh['start'],sh['stop']) )
                        flShInfo = [{'name':sh['name'], 'color':sh['color'], 'start':sh['start'], 'stop':sh['stop']}]
                    MC.file( rename=os.path.join(shotsDir ,'%s_SHOT_%s.ma'%(scene_name.replace('.ma',''), sh['name'].replace('SH0T_','') ) ))
                    self.generateTimeMarks(flShInfo)
                    self.saveData(flShInfo)
                    shotf = os.path.abspath(MC.file( save=True, type='mayaAscii' ))
                    shotFiles.append(shotf)

                    amount = 100 / shotCount * float(idx)
                    MC.progressWindow(edit=True, progress=amount, status='proceed: %d%%' % amount)
                    UT.processIdleEvents()
                
                MC.progressWindow(endProgress=1)
                MC.file( force=True, new=True )
                # flname = os.path.join(scene_path, scene_name)
                # MC.file(flname, open=True, force=True, options='v=0;', ignoreVersion=1, prompt=False, loadReferenceDepth='none', reserveNamespaces=1, typ='mayaAscii')

            if makeclean:
                tittle = 'Clean shot files'
                MC.progressWindow(title=tittle, progress=0, status='proceed: 0%', isInterruptable=True)
                shotFilesCount = len(shotFiles)
                print ('HZ Shot Exporter => Begin...')
                for idx, fl in enumerate(shotFiles):
                    if self.checkProgressEscape(): return
                    cmand = "%s \"%s\" \"%s\" \"%s\""%(mayaPath,batchScriptPath,fl,nestedRefTxt)
                    # print (cmand)
                    CREATE_NO_WINDOW = 0x08000000
                    maya = subprocess.Popen(cmand,stdout=subprocess.PIPE,stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
                    out,err = maya.communicate()
                    exitcode = maya.returncode
                    if str(exitcode) != '0':
                        #print(err)
                        print ("%s <<< file: %s" % (err, fl))
                        # pass
                    else:
                        print ('%s DONE' % (out))
                    with open(fl) as f:
                        newText=f.read()
                    regex = r"^(file\s-rdi.*)(-dr\s1\s)(-rfn\s)"
                    subst = "\\1\\3"
                    newText = re.sub(regex, subst, newText, 0, re.MULTILINE)
                    with open(fl, "w") as f:
                        f.write(newText)
                    amount = 100 / shotFilesCount * float(idx)
                    MC.progressWindow(edit=True, progress=amount, status='proceed: %d%%' % amount)
                    UT.processIdleEvents()

                print ('HZ Shot Exporter => Finish.')
                MC.progressWindow(endProgress=1)

            conf = MC.layoutDialog(ui=self.checkboxPrompt, t='process is DONE')
            if conf == 'open':
                FILEBROWSER_PATH = os.path.join(os.getenv('WINDIR'), 'explorer.exe')
                #print(shotsDir)
                path = os.path.abspath(shotsDir)
                if os.path.isdir(path):
                    subprocess.call([FILEBROWSER_PATH, path])
                elif os.path.isfile(path):
                    subprocess.call([FILEBROWSER_PATH, '/select,', os.path.normpath(path)])
            if conf!='continue':
                if MC.window(self.__WINDOW_NAME, exists = True): MC.deleteUI(self.__WINDOW_NAME)                    

        except Exception as e:
            # print(traceback.format_exc())
            raise e
        finally:
            MC.refresh(su=False)

    def loadTextdata(self, *args):
        jsonText = json.dumps(self.loadData(), sort_keys=True, indent=2, separators=(',', ': '))
        MC.scrollField(self.txt_alldata, e=1, text=jsonText)

    def saveTextdata(self, *args):
        newData = MC.scrollField(self.txt_alldata, q=1, text=1)
        newData = ("".join(newData.strip()).encode('ascii', 'ignore').decode("utf-8")).replace("\\","")
        if not newData: 
            return MC.warning('No new Data Saved!')
        try:
            newdt = json.loads(newData)
            self.saveData(newdt)
            self.loadTextdata()
            print("New Data replaced successfuly."),
        except ValueError as e:
            return MC.error('Data Has Error in reading. No new Data Saved!')

    def checkboxPrompt(self):
        form = MC.setParent(q=True)
        MC.formLayout(form, e=True, width=300)
        t = MC.text(l='Shot Export process is DONE.', font='boldLabelFont')
        s1 = MC.separator()
        t2 = MC.text(l='What do you want to do?')
        b1 = MC.button(l='Just close', c='maya.cmds.layoutDialog( dismiss="close" )' )
        b2 = MC.button(l='Open folder', c='maya.cmds.layoutDialog( dismiss="open" )' )
        b3 = MC.button(l='Try another', c='maya.cmds.layoutDialog( dismiss="continue" )' )
        spacer = top = edge = 5
        MC.formLayout(form, edit=True,
                        attachForm=[(t, 'top', top), (t, 'left', edge), (t, 'right', edge), (b1, 'left', edge), (b3, 'right', edge),
                                    (t2, 'top', top), (t2, 'left', edge), (t2, 'right', edge), (s1, 'top', top), (s1, 'left', edge), (s1, 'right', edge)],
                        attachNone=[(t, 'bottom'),(t2, 'bottom'), (b1, 'bottom'), (b2, 'bottom'), (b3, 'bottom'), ],
                        attachControl=[(b1, 'top', spacer*2, t2), (b2, 'top', spacer*2, t2), (b3, 'top', spacer*2, t2), (t2, 'top', spacer, s1), (s1, 'top', spacer, t)],
                        attachPosition=[(b1, 'right', spacer, 33), (b2, 'left', spacer, 33), (b2, 'right', spacer, 66), (b3, 'left', spacer, 66)])

    def hzasgFrms(self, *args):
        # MC.scrollField(self.excelPaste, e=1, cl=True)
        excelcopypaste = MC.scrollField(self.excelPaste,q=1, text=1)
        if not excelcopypaste:
            frameLens = map(str,self.extractNumbers(self.get_clipboard_text()))
        else:
            frameLens = map(str,self.extractNumbers(excelcopypaste))
        MC.scrollField(self.excelPaste,e=1, text=' '+'    '.join(frameLens)+' ')

    def hzasgNodes(self, *args):
        __cams = MC.listCameras( p=True )
        selected = (MC.ls(sl=1, head=1) or [''])[0]
        if selected in __cams:
            MC.nameField(self.objsName, e=1, object=selected)

    def hzCalcPrevs(self, *args):
        prevexcelcopypaste = MC.scrollField(self.prevExcelPaste,q=1, text=1)
        if not prevexcelcopypaste:
            prevframeLens = self.extractNumbers(self.get_clipboard_text())
        else:
            prevframeLens = self.extractNumbers(prevexcelcopypaste)
        if prevframeLens:
            MC.scrollField(self.prevExcelPaste,e=1, text=' '+'   '.join(map(str,prevframeLens))+' ')
            MC.intField(self.frmOfset, e=1, v=sum(prevframeLens))
            MC.intField(self.shotNum, e=1, v=len(prevframeLens)+1)

    def hzClearPrevs(self, *args):
        MC.scrollField(self.prevExcelPaste,e=1,clear=1)

    def showUI(self):    
        if MC.window(self.__WINDOW_NAME, exists = True): MC.deleteUI(self.__WINDOW_NAME)
        window = MC.window( self.__WINDOW_NAME, title = "Shot Manager v%s"%self.__version__, maximizeButton=0, sizeable=1)
        windowWidth = 300
        mainlayout = MC.formLayout()
        labout = MC.text(l="H.Z. Shot Manager v%s"%self.__version__, font='tinyBoldLabelFont')            
        babout = MC.button(l='About', h=15, w=50, bgc=self.hex2rgb('80aaff'), 
                    c= lambda *args: MC.layoutDialog(ui=self.showAbout,t='About', bgc=self.hex2rgb('80aaff')) )
        tabs = MC.tabLayout(innerMarginWidth=5, innerMarginHeight=5, w=windowWidth)                    
        MC.formLayout(mainlayout, edit=True,   
                    attachForm=[(labout, 'top', 5), (labout, 'left', 5), (babout, 'right', 5), (babout, 'top', 5),
                                (tabs, 'top', 20), (tabs, 'left', 5), (tabs, 'right', 5), (tabs, 'bottom', 5)])              

        creatorTab = MC.columnLayout(adj=1,columnWidth=windowWidth,columnAttach=('both', 5), rowSpacing=10 ) 
        MC.text(l="", h=10)
        with self.HZCRow(creatorTab, 3, [75,150,75]):
            MC.text(l="Camera:")
            self.objsName = MC.nameField()
            MC.button(h=20, c=self.hzasgNodes, l=" <<< ", ann=" Add Selected Camera ", w=50) 
        with self.HZCRow(creatorTab, 5, [110,60,20,90,20], adjustableColumn=3):
            MC.text(l="Start frame Offset:")
            self.frmOfset = MC.intField(v=0)
            MC.text(l='<')
            self.prevExcelPaste = MC.scrollField(h=30, w=90, editable=True, wordWrap=False )
            MC.button(l='X',c=self.hzClearPrevs,h=30)
        with self.HZCRow(creatorTab, 4, [110,60,20,110], adjustableColumn=3):
            MC.text(l="Start Shot NUMBER:")
            self.shotNum = MC.intField(v=1, min=1)
            MC.text(l='<')
            MC.button(ann="Select all PREVIOUS SHOTS LENGHT to clipboard then press calculate bottom to fill the fileds or fill them manually",
                 l="Calculate",c=self.hzCalcPrevs, w=110)
        with self.HZCRow(creatorTab, 3, [75,100,75]):
            MC.text(l="Shot Lenghts:")
            self.excelPaste = MC.scrollField(h=30, editable=True, wordWrap=False )
            MC.button(ann=" Paste Frame Numbers ", l=" Paste ", w=50, c=self.hzasgFrms)
        MC.button(c=self.createShots, l="CREATE Shots", backgroundColor= self.hex2rgb('00bfff') , w=120, h=50)
        MC.text(l="", h=1)
        MC.setParent( u=1 )

        exporterTabForm = MC.columnLayout(adj=1,columnWidth=windowWidth, columnAttach=('both', 5), rowSpacing=10 )
        MC.text(l='', h=2)
        MC.text(l='Important Note:\n. All `Anim Layers` should be UNLOCKed.', al='left', font='boldLabelFont')
        MC.text(l='', h=2)
        MC.text(l='Exporting Steps:', al='left')
        with self.HZCRow(exporterTabForm, 3, [160,75,10], adjustableColumn=3):
            MC.checkBox(l="Start OFFSET of each shot:", v=1,
                        onc=lambda *args: MC.intField(self.expoOfset, e=1, en=1),
                        ofc=lambda *args: MC.intField(self.expoOfset, e=1, en=0) )
            self.expoOfset = MC.intField(v=1000)
            MC.text(l='')
        self.chk_steps = MC.checkBoxGrp(vertical=1, numberOfCheckBoxes=3, 
                                    labelArray3=['Set Keyframes for Shots', 
                                                'Create every shots and make unique file for each', 
                                                'Clean any keyframes out of own time range.'],
                                    valueArray3=[True]*3 , cl3=['left']*3, 
                                    of2=lambda *args: MC.checkBoxGrp(self.chk_steps, e=1, en3=0, v3=0), 
                                    on2=lambda *args: MC.checkBoxGrp(self.chk_steps, e=1, en3=1), )
        MC.button(c=self.exportShots, l="EXPORT Shots", backgroundColor= self.hex2rgb('ff0040') , w=120, h=50)
        MC.text(l="", h=1)
        MC.setParent( u=1 )

        extraTab = MC.columnLayout(adj=1,columnWidth=windowWidth,columnAttach=('both', 5), rowSpacing=10)
        MC.text(l="", h=20)
        MC.button(l='Setup Animation Camera', ann="Configure selected camera", h=40, c=self.setupAnimCam,bgc=self.hex2rgb('003311'))
        MC.button(l="Regenerate Timiline Bookmarks",bgc=self.hex2rgb('003311'), h=40
                , ann="In maya version before 2020 it only sets keyframes for animation camera.\n"
                    "But if timeline marker (gum.co/maya-timeline-marker) had been installed,\n"
                    "HZShotManager makes timeline marker using that."
                , c=self.generateTimeMarks )
        MC.button(l="Set Keyframes for Shots", ann='Set keyframe everytings at start and end of shot.', h=40, c=self.setKeyShots, bgc=self.hex2rgb('003311'))
        MC.setParent( u=1 )

        editTab = MC.columnLayout(adj=1,columnWidth=windowWidth,columnAttach=('both', 5), rowSpacing=10)
        MC.text(l="", h=5)
        self.txt_alldata = MC.scrollField( editable=True, wordWrap=False, font='smallFixedWidthFont' )
        with self.HZCRow(editTab, 3, [100,75,100], adjustableColumn=3):
            MC.button(c=self.loadTextdata, l="Load Data", backgroundColor= self.hex2rgb('00bfff') , w=120, h=20)
            MC.text(l='')
            MC.button(c=self.saveTextdata, l="Save Data", backgroundColor= self.hex2rgb('ff0040') , w=120, h=20)
        MC.setParent( u=1 )

        MC.tabLayout( tabs, edit=True, tabLabel=((creatorTab,'Create Shots'), (exporterTabForm,'Export Shots'),
                                             (extraTab,'Extras'), (editTab,'Data (Adv. only)')) )
        MC.showWindow( window )
        MC.window( window, edit=True, h=250, resizeToFitChildren=1)

if __name__ != "__main__":
    pass
