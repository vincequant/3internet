#!/bin/bash
# Shared env for shadow tools (LOCAL Mac build - three-client lab).
export WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow"
export WINEDEBUG=-all
export DYLD_FALLBACK_LIBRARY_PATH="$HOME/Library/Application Support/SGI-Wine/dependency-lib"
unset DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH DYLD_INSERT_LIBRARIES
export S="$HOME/sgi-fengye-lab/shadow"
export P32="$HOME/sgi-fengye-lab/python32/python.exe"
export WINE="$HOME/Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wine"
export Z='Z:\Users\vk\sgi-fengye-lab\shadow'
# local three-client layout: host (dingman) + fengyun + shadow
export HOST_PREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-dingman-local"
export FENGYUN_PREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-sikarugir10"
