# creation date : 28 May, 2022
#
# Author :    Hamed Zandieh
# Contact :   hamed.zandieh@gmail.com
#
# Description :
#    This script create is part of HZshotExporter.py
# 

import sys, os
import maya.standalone as std
std.initialize(name='python')
import maya.cmds as cmds
import maya.utils as utils

finame = sys.argv[1]
withrefs = sys.argv[2]

def cleanOutofPlayBacks(filename, loadRefs):
    try:
        cmds.file(filename, open=True, force=True, options='v=0;', ignoreVersion=1, 
                    prompt=False, loadReferenceDepth='none', reserveNamespaces=1, typ='mayaAscii')  
        if loadRefs:
            refs = loadRefs.split(',')
            for r in refs:
                cmds.file(loadReference=r, loadReferenceDepth='topOnly')
        scene_name = os.path.basename(filename)
        start = cmds.playbackOptions(query=True, min=True)
        end = cmds.playbackOptions(query=True, max=True)
        allanimCurvesinScene = cmds.ls(type=['animCurveTL','animCurveTA','animCurveTU'])
        cmds.cutKey(clear=1, time=(-100000,start-1), *allanimCurvesinScene) 
        cmds.cutKey(clear=1, time=(end+1,100000), *allanimCurvesinScene) 
        utils.processIdleEvents()
        cmds.file(s=1, f=True) 
        sys.stdout.write(scene_name)
        return scene_name
    except Exception as e:
        sys.stderr.write(str(e))
        sys.exit(-1)

cleanOutofPlayBacks(finame, withrefs)