[app]
title = RemoteLink
package.name = remotelink
package.domain = org.remotelink

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 1.0

requirements = python3,kivy==2.3.0,websockets,pillow,numpy,pyjnius,android

# Orientation
orientation = portrait

# Android
android.permissions = INTERNET,RECORD_AUDIO,FOREGROUND_SERVICE,SYSTEM_ALERT_WINDOW
android.api = 33
android.minapi = 21
android.ndk = 25b
android.sdk = 33
android.archs = arm64-v8a, armeabi-v7a

android.allow_backup = True
android.manifest.intent_filters = 
android.add_jars = 

# Fullscreen
fullscreen = 0

# Icons (optional - add your own)
# icon.filename = %(source.dir)s/icon.png
# presplash.filename = %(source.dir)s/presplash.png

[buildozer]
log_level = 2
warn_on_root = 1
