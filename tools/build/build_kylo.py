# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/. 
# 
# Copyright 2005-2012 Hillcrest Laboratories, Inc. All rights reserved. 
# Hillcrest Labs, the Loop, Kylo, the Kylo logo and the Kylo cursor are 
# trademarks of Hillcrest Laboratories, Inc.

from common import build_prefs, build_util, omnify
from common.build_prefs import Settings
from optparse import OptionParser
from ConfigParser import ConfigParser
import errno
import os
import shutil
import fileinput
import filecmp
import stat
import sys
from datetime import datetime

# ----------------------
# Only platform specific lines here
if sys.platform == 'darwin':
    from mac import platform_build
if sys.platform == 'win32':
    from win32 import platform_build
# ----------------------

logger = None

# ----------------------
def build():
    """Build Kylo according to program inputs"""
    
    # Update the build and dist directories to include platform info and product id
    Settings.prefs.build_dir = os.path.normpath(os.path.join(Settings.prefs.build_dir, Settings.platform, Settings.config.get('App', 'ProdID')))
    Settings.prefs.dist_dir  = os.path.normpath(os.path.join(Settings.prefs.dist_dir,  Settings.platform, Settings.config.get('App', 'ProdID')))
    
    # Set the path to the selected version of the XULRunner runtime
    Settings.prefs.xul_dir   = os.path.abspath(os.path.join(Settings.prefs.moz_dir, "xulrunner"))
    
    # Set the path to the selected version of the Gecko SDK
    Settings.prefs.sdk_dir   = os.path.abspath(os.path.join(Settings.prefs.moz_dir, "xulrunner-sdk"))

    # Kylo source goes into different directories depending on platform
    if Settings.platform == "osx":
        kylo_build_dir = os.path.join(Settings.prefs.build_dir, "Kylo.app")
    else: # win32, linux, etc.
        kylo_build_dir = os.path.join(Settings.prefs.build_dir, "application")
        
    Settings.prefs.kylo_build_dir = kylo_build_dir

    # Clean up previous builds
    if Settings.prefs.clean:
        path = Settings.prefs.build_dir
        if os.path.exists(path):
            logger.info("Cleaning directory: %s", path)
            shutil.rmtree(path, ignore_errors=False, onerror=build_util.RMFail)
        
        # Clean up binary components
        for component in Settings.config.options('components'):
            platform_build.cleanComponent(component)
            
        # Clean up binary components in extensions
        for ext in Settings.config.options('extensions'):
            ext_components_dir = os.path.join(Settings.prefs.src_dir, "extensions", ext, "components")
            if os.path.isdir(ext_components_dir):
                for component in os.listdir(ext_components_dir):
                    if os.path.isdir(os.path.join(ext_components_dir, component)):
                        platform_build.cleanComponent(component, componentDir=os.path.join(ext_components_dir, component))       
        
        # Check to see if we should clean the dist directory too                                                  
        if Settings.prefs.clean_dist:
            path = Settings.prefs.dist_dir
            if os.path.exists(path):
                logger.info("Cleaning output directory: %s", path)
                shutil.rmtree(path, ignore_errors=False, onerror=build_util.RMFail)
    
    # ---------------------
    # Build C++ components
    if len(Settings.prefs.compile) > 0:
        logger.info("=" * 72)
        logger.info("Building C++ Components: %s" % Settings.prefs.compile)
        logger.info("=" * 72)
        
        # Build main set of components
        if "com" in Settings.prefs.compile:
            for component in Settings.config.options('components'):
                if not Settings.prefs.clean:
                    platform_build.cleanComponent(component)
                platform_build.buildComponent(component)
        
        # Build extensions' components
        if "ext" in Settings.prefs.compile:
            for ext in Settings.config.options('extensions'):
                ext_components_dir = os.path.join(Settings.prefs.src_dir, "extensions", ext, "components")
                if os.path.isdir(ext_components_dir):
                    for component in os.listdir(ext_components_dir):
                        if os.path.isdir(os.path.join(ext_components_dir, component)):
                            if not Settings.prefs.clean:
                                    platform_build.cleanComponent(component, componentDir=os.path.join(ext_components_dir, component))
                            for part in platform_build.buildComponent(component, componentDir=os.path.join(ext_components_dir, component)):
                                shutil.copy2(part, ext_components_dir)
            
    # ---------------------
    # Copy source materials into our build directory
    if Settings.prefs.update:
        # Start counting how many updates we do...
        numUpdates = 0
        
        kylo_src_dir = os.path.join(Settings.prefs.src_dir, "kylo")
        
        # Create build_dir if it doesn't exist
        if not os.path.exists(Settings.prefs.build_dir):
            logger.info("Creating build directory: %s", Settings.prefs.build_dir)
            os.makedirs(Settings.prefs.build_dir)
            numUpdates += 1
            
        
        # Check if we have an existing omni.ja[r]
        omni_path = os.path.join(Settings.prefs.kylo_build_dir, "omni.jar")
        if os.path.isfile(omni_path) or os.path.isfile(omni_path[:-1]):
            # delete the chrome.manifest, because it's been tainted by the 
            # omni.jar process
            del_files = ["chrome.manifest"]
            
            if not Settings.prefs.omnify:
                # if we're not omnify-ing again, delete the old jar
                del_files += ["omni.jar", "omni.ja"]
                
            for f in del_files:
                file = os.path.join(Settings.prefs.kylo_build_dir, f)
                if (os.path.isfile(file)):
                    logger.info("Cleaning up - deleting %s" % file)
                    os.remove(file)
            
        # Sync our source directory
        logger.info("Copying Kylo source from %s to %s" % (kylo_src_dir, kylo_build_dir))
        syncSrcReport = build_util.syncDirs(kylo_src_dir, kylo_build_dir, purge=False, force_write=True, exclude=[".hc.copyright.rules", "application.ini"])
        numUpdates += sum(syncSrcReport[1:])
        
        # Copy Component outputs into BUILD_DIR
        logger.info("Copying components into build directory...")
        component_build_dir = os.path.join(kylo_build_dir, "components")
        binary_mfst_contents = []
        mfst_count = 0
        for component in Settings.config.options('components'):
            # Copy binaries first
            compDir = os.path.join(Settings.prefs.src_dir, "components", component)
            binDir = os.path.join(compDir, "bin")
            for f in [os.path.join(binDir, pattern % component) \
                          for pattern in ('%s.dll', '%s.dylib', '%s.so', 'I%s.xpt')]:
                if os.path.exists(f):
                    if build_util.syncFile(f, component_build_dir):
                        logger.info("Copied %s to %s" % (os.path.basename(f), component_build_dir))
                        numUpdates += 1
                    
            # Grab component-specific manifests
            mfst = os.path.join(compDir, "%s.manifest" % component)
            if os.path.isfile(mfst):
                if (mfst_count):
                    binary_mfst_contents.append("\r\n")
                binary_mfst_contents.append("# %s.manifest" % component)
                mfst_file = open(mfst, 'r')
                for line in mfst_file.readlines():
                    if not line.startswith("#"):
                        binary_mfst_contents.append(line)
                #binary_mfst_contents.extend(mfst_file.readlines())
                mfst_file.close()
                
                # increment our counter
                mfst_count += 1
            
            # Grab component-specific preferences
            pref = os.path.join(compDir, "%s-prefs.js" % component)
            if os.path.isfile(pref):
                outpref = os.path.join(kylo_build_dir, "defaults", "preferences")
                if build_util.syncFile(pref, outpref, force_write=True):
                    numUpdates += 1

        # Write binary.manifest
        if len(binary_mfst_contents) > 0:
            logger.info("Writing binary.manifest")
            
            bin_mfst_path = os.path.join(kylo_build_dir, "components", "binary.manifest")
            
            if os.path.exists(bin_mfst_path):
                logger.info("... writing temp file")
                temp_bin_mfst_path = os.path.join(kylo_build_dir, "components", "~binary.manifest")
                temp_binary_mfst = open(temp_bin_mfst_path, "w+")
                temp_binary_mfst.writelines(binary_mfst_contents)
                temp_binary_mfst.close()
                
                logger.info("... comparing temp")
                if not filecmp.cmp(temp_bin_mfst_path, bin_mfst_path, shallow=False):
                    logger.info("... replacing original with temp")
                    os.remove(bin_mfst_path)
                    os.rename(temp_bin_mfst_path, bin_mfst_path)
                    numUpdates += 1
                else:
                    logger.info("... temp same as original")
                    os.remove(temp_bin_mfst_path)
            else:
                binary_mfst = open(bin_mfst_path, "w+")
                binary_mfst.writelines(binary_mfst_contents)
                binary_mfst.close()
                numUpdates += 1
            
            
            
        # Copy extensions into BUILD_DIR
        logger.info("Copying extensions into build directory...")
        extensions_build_dir = os.path.join(kylo_build_dir, "extensions")
        for ext in Settings.config.options('extensions'):
            ext_src = os.path.join(Settings.prefs.src_dir, "extensions", ext)
            ext_build = os.path.join(extensions_build_dir, ext)
            syncExtReport = build_util.syncDirs(ext_src, ext_build, purge=True, force_write=True, exclude=[".hc.copyright.rules", "components"])
            numUpdates += sum(syncExtReport[1:])
            
            # Handle components directory separately to avoid syncing binary source
            ext_com_src = os.path.join(ext_src, "components")
            if os.path.isdir(ext_com_src):
                ext_com_build = os.path.join(ext_build, "components")
                if not os.path.isdir(ext_com_build):
                    os.makedirs(ext_com_build)
                    numUpdates += 1
                for f in os.listdir(ext_com_src):
                    if os.path.isfile(os.path.join(ext_com_src, f)):
                        if build_util.syncFile(os.path.join(ext_com_src, f), ext_com_build):
                            logger.info("--> copied %s" % f)
                            numUpdates += 1
                
        # ---------------------
        # Create our application.ini
        # TODO: May want to move this under buildApp()
        logger.info("Creating application.ini...")
        ini = ConfigParser(allow_no_value=True)
        ini.optionxform = str
        
        sections = ('App', 'Gecko', 'Crash Reporter', 'XRE')
        for section in sections:
            ini.add_section(section)
            opts = Settings.config.items(section)
            for (opt, val) in opts:
                ini.set(section, opt, val)
        
        ini_path = os.path.join(kylo_build_dir, "application.ini")
        
        if os.path.exists(ini_path):
            logger.info("... writing temp file")
            temp_ini_path = os.path.join(kylo_build_dir, "~application.ini")
            temp_ini_file = open(temp_ini_path, "w+")
            ini.write(temp_ini_file)
            temp_ini_file.close()
            
            for line in fileinput.input(temp_ini_path, inplace=1):
                print line.replace(" = ", "="),
            
            logger.info("... comparing temp")
            if not filecmp.cmp(temp_ini_path, ini_path, shallow=False):
                logger.info("... replacing original with temp")
                os.remove(ini_path)
                os.rename(temp_ini_path, ini_path)
                numUpdates += 1
            else:
                logger.info("... temp same as original")
                os.remove(temp_ini_path)
        else:
            ini_file = open(ini_path, "w+")
            ini.write(ini_file)
            ini_file.close()
            
            # Seems to be a weird incompatibility - ConfigParser writes values as "name = value", but XUL runner needs "name=value" (no spaces)
            for line in fileinput.input(ini_path, inplace=1):
                print line.replace(" = ", "="),
                
            numUpdates += 1     

        logger.info("### Number of updates: %d" % numUpdates)

    # ---------------------
    # Jar up the app
    if Settings.prefs.update and Settings.prefs.omnify:
        logger.info("Creating omni.jar/omni.ja")
        if numUpdates > 0:
            omnify.makejar()
        else:
            logger.info("... skipping, nothing to add to jar")
        
    # ---------------------
    # We're going to leave the binary.manifest in the components directory
    # and reference it from a new/modified chrome.manifest in root.
    if os.path.isfile(os.path.join(Settings.prefs.kylo_build_dir, "components", "binary.manifest")):
        chrome_mfst = open(os.path.join(Settings.prefs.kylo_build_dir, "chrome.manifest"), "a+")
        found = False
        line_count = 0
        for line in chrome_mfst:
            line_count += 1
            if "binary.manifest" in line:
                found = True
                break
        if not found:
            if line_count > 0:
                chrome_mfst.write("\n")
            chrome_mfst.write("manifest    components/binary.manifest")
        chrome_mfst.close()    

    # ---------------------
    # Build the app itself
    if Settings.prefs.buildapp:
        logger.info("Building Kylo")
        platform_build.buildApp()

    # ---------------------
    # Prep installer
    if Settings.prefs.installer:
        logger.info("Create installer")
        platform_build.buildInstaller()
        
        
    # ---------------------
    # Kill the logging
    logger.info("=" * 72)
    logger.info("Build Complete!")
    build_util.stopLogging()
    
    return

def init(args = None):
    usage = "Build The Kylo Browser.\n"\
            "\tusage: %prog [options] configfile [configfile [configfile...]]"
    parser = OptionParser(usage=usage)

    # Log defaults
    parser.set_defaults(verbosity="info")
    parser.set_defaults(logfile=None)
    
    # Clean defaults
    parser.set_defaults(clean=False)
    parser.set_defaults(clean_dist=False)
    
    # Build defaults
    parser.set_defaults(update=True)
    parser.set_defaults(omnify=True)
    parser.set_defaults(compile=[])
    parser.set_defaults(buildapp=False)
    parser.set_defaults(installer=False)
    
    # Path defaults
    ROOT_DIR = os.path.abspath("../..")
    parser.set_defaults(root_dir=ROOT_DIR)
    parser.set_defaults(src_dir=os.path.abspath(os.path.join(ROOT_DIR, "src")))
    parser.set_defaults(build_dir=os.path.abspath(os.path.join(ROOT_DIR, "build")))
    parser.set_defaults(dist_dir=os.path.abspath(os.path.join(ROOT_DIR, "dist")))
    parser.set_defaults(bin_dir=os.path.abspath(os.path.join(ROOT_DIR, "bin")))
    parser.set_defaults(moz_dir=os.path.abspath(os.path.join(ROOT_DIR, "src")))
    
    # Identity defaults (set to None - defaults come from config files)
    parser.set_defaults(version=None)
    parser.set_defaults(buildid=None)
    parser.set_defaults(prodid=None)
    parser.set_defaults(gecko=None) 
    parser.set_defaults(revision=None)   
    
    # TODO: Handle language packs
    #parser.set_defaults(langs=[])

    # ---------------------
    # Verbosity options
    parser.add_option("-v", "--verbose",
                      action="store_const",
                      dest="verbosity",
                      const="debug",
                      help="Print lots of information while building. " + \
                            "Equivalent to --verbosity=debug")
    
    parser.add_option("-q", "--quiet",
                      action="store_const",
                      dest="verbosity",
                      const="critical",
                      help="Disable informational messages while building. " + \
                      "Equivalent to --verbosity=critical")

    parser.add_option("--verbosity",
                      dest="verbosity",
                      choices=["debug", "info",
                               "warning", "error",
                               "critical"],
                      help="Set level of informational messages to print. " + \
                      "One of 'debug','info','warning','error','critical'. " + \
                      "Default is 'info'")
    
    parser.add_option("--logfile",
                      dest="logfile",
                      type="string",
                      help="Output the log to a specific file. Logs to stdout if not set.")

    # ---------------------
    # Directory options (root, build, src, bin, dist, moz)
    parser.add_option("--root-dir",
                      dest="root_dir",
                      type="string",
                      metavar="ROOT_DIR",
                      help="Use sources from ROOT_DIR. " + \
                      "(ROOT_DIR contains src, build, dist, bin). " + \
                      "Default is '..'")
    
    parser.add_option("--build-dir",
                      dest="build_dir",
                      type="string",
                      metavar="BUILD_DIR",
                      help="Use BUILD_DIR as staging directory for builds. " + \
                      "Default is '../build'")
    
    parser.add_option("--src-dir",
                      dest="src_dir",
                      type="string",
                      metavar="SRC_DIR",
                      help="SRC_DIR contains source code for Kylo, extensions and components. " + \
                      "Default is '../src'")
      
    parser.add_option("--dist-dir",
                      type="string",
                      dest="dist_dir",
                      metavar="DIST_DIR",
                      help="Put executable or installer in DIST_DIR. " + \
                      "Default is '../dist'")  
    
    parser.add_option("--moz-dir",
                      type="string",
                      dest="moz_dir",
                      metavar="MOZ_DIR",
                      help="Parent directory of 'xulrunner' and 'xulrunner-sdk'. " + \
                      "Default is '../src'")      
    
    # ---------------------
    # Clean options
    parser.add_option("--clean",
                      dest="clean",
                      action="store_true",
                      help="Deletes existing build and bin" + \
                      "directories, exits build process.")
        
    parser.add_option("--clean-dist",
                      dest="clean_dist",
                      action="store_true",
                      help="Deletes files within DIST_DIR. If not specified, " + \
                      "DIST_DIR is excluded from normal clean up process.")
    
    # ---------------------
    # Build options (skip-update, skip-omni, compile, app, installer)
    parser.add_option("--skip-update",
                      dest="update",
                      action="store_false",
                      help="If the BUILD_DIR already contains files copied from the SRC_DIR " + \
                      "this will prevent them from being copied over with latest.")
    
    parser.add_option("--skip-omni",
                      dest="omnify",
                      action="store_false",
                      help="Prevents application source being compressed into a single omni.jar file.")
    
    parser.add_option("-c", "--compile",
                      action="store_const",
                      dest="compile",
                      const=["ext", "com"],
                      help="Compile all XPCOM components in the 'components' and 'extensions' directories. " + \
                      "NOTE: skipping this option may " + \
                      "produce errors if pre-compiled libraries " + \
                      "do not already exist in their appropriate bin directories")
    
    parser.add_option("--compile-ext",
                      action="append_const",
                      dest="compile",
                      const="ext",
                      help="Compile XPCOM components in the 'extensions' directory ONLY.")
    
    parser.add_option("--compile-com",
                      action="append_const",
                      dest="compile",
                      const="com",
                      help="Compile XPCOM components in the 'components' directory ONLY.")
          
    parser.add_option("--app",
                      dest="buildapp",
                      action="store_true",
                      help="Create the Kylo executable (.exe, .app, etc.)")    
    
    parser.add_option("-i", "--installer",
                      action="store_true",
                      dest="installer",
                      help="Create the installer file (NSIS on Windows, DMG on OS X).")
    
    # ---------------------
    # Identity options (build id, product id, version)
    parser.add_option("-B", "--build-id",
                      dest="buildid",
                      type="string",
                      help="Build Number. Overrides the 'BuildID' value, under 'App', " + \
                      "in the config file.")
    
    parser.add_option("-P", "--product-id",
                      type="string",
                      dest="prodid",
                      help="Product id. Default is 'kylo'. Can be alphanumeric string, " + \
                      "no spaces. Overrides the ProdID value, under App, in the config file.")    
    
    parser.add_option("-V", "--version",
                      dest="version",
                      type="string",
                      help="The version of Kylo that is being built. Overrides the " + \
                      "'Version' value, under 'App', in the config file.")    
    
    parser.add_option("-G", "--gecko-version",
                      type="string",
                      dest="gecko",
                      help="Version of the XUL SDK to compile against. Overrides the " + \
                      "'gecko' value, under 'Build', in the config file.")    
    
    parser.add_option("-R", "--revision",
                      type="string",
                      dest="revision",
                      help="Revision number - tacked on as the last value in the version string. " + \
                      "Like 1.0.1[.123456]. Should be a changelist number.")

    (options, args) = parser.parse_args(args = args)        
    Settings.prefs = options
    
    if len(args) < 1:
        parser.error("Incorrect number of arguments")
        
    # Save the platform in a convenient string
    if sys.platform == "win32":
        Settings.platform = "win32"
    elif sys.platform == "darwin":
        Settings.platform = "osx"
    elif sys.platform.startswith("linux"):
        Settings.platform = "linux"
    else:
        Settings.platform = sys.platform           
    
    # New config parser, allows options without values and forces case-sensitive options
    conf = ConfigParser(allow_no_value=True)
    conf.optionxform = str
    
    # Grab platform config
    platformConf = os.path.join(Settings.platform, "%s.platform.conf" % Settings.platform)
    if os.path.isfile(platformConf):
        conf.readfp(open(platformConf))
    
    # Suck in application.ini file as config
    appini = os.path.normpath(os.path.join(Settings.prefs.src_dir, "kylo", "application.ini"))
    if os.path.isfile(appini):
        conf.readfp(open(appini))
    
    # Read the first config file passed in as argument
    conf.readfp(open(os.path.abspath(args[0])))
    
    # Loop through other config file arguments
    if len(args) > 1:
        cfgs = [os.path.abspath(cfg) for cfg in args[1:]]
        conf.read(cfgs)    
    
    Settings.config = conf
    
    # Set some overrides
    if Settings.prefs.prodid:
        Settings.config.set("App", "ProdID", Settings.prefs.prodid)
    if Settings.prefs.buildid:
        Settings.config.set("App", "BuildID", Settings.prefs.buildid)
    else:
        # Default build id is current time stamp
        Settings.config.set("App", "BuildID", datetime.now().strftime("%Y%m%d%H%M%S"))
    if Settings.prefs.version:
        Settings.config.set("App", "Version", Settings.prefs.version)
    if Settings.prefs.gecko:
        Settings.config.set("Build", "gecko", Settings.prefs.gecko)

    # Tack on the revision number (if provided)
    if Settings.prefs.revision:
        v = Settings.config.get("App", "Version")
        Settings.config.set("App", "Version", "%s.%s" % (v, Settings.prefs.revision))
    
    # If we're cleaning, skip other options automatically
    if Settings.prefs.clean:
        Settings.prefs.compile = ()
        Settings.prefs.update = False
        Settings.prefs.omnify = False
        Settings.prefs.buildapp = False
        Settings.prefs.installer = False
        
    global logger
    logger = build_util.getLogger("build_kylo")
    sys.stdout = build_util.StreamLogger(sys.stdout, logger, prefix='[stdout] ')
    sys.stderr = build_util.StreamLogger(sys.stderr, logger, prefix='[stderr] ')

    logger.info('=' * 72)
    logger.info(' Making a %s %s build' % (Settings.platform, Settings.config.get("App","ProdID")))
    logger.info(' source dir: %s' % Settings.prefs.src_dir)
    logger.info(' build dir:  %s' % Settings.prefs.build_dir)
    logger.info(' dist dir:   %s' % Settings.prefs.dist_dir)
    logger.info('=' * 72)

    
################# Main - courtesy of Guido ###############################
## http://www.artima.com/weblogs/viewpost.jsp?thread=4829
    
def main():
    try:    
        init()
        build()        

    except IOError, err:
        print "IO error(%s): %s - '%s'"%(err.errno, err.strerror, err.filename)
        return 2

if __name__ == "__main__":
    sys.exit(main())

