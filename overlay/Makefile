# Source Yaw overlay layer (GPL-3.0, forked from KROSSHAIR v0.2.5).
# Builds against the bundled Vulkan headers by default.
LIBRARY = lib/sourceyaw-overlay.so
# the Vulkan headers this was built with ship in include/ (Apache-2.0 OR MIT)
VULKAN_INCLUDE ?= ./include

CFLAGS = -Wall -std=gnu99 -fPIC -shared -fvisibility=hidden -O2 -DNDEBUG -I./include -I$(VULKAN_INCLUDE)
LDFLAGS = -ldl -lm -lpthread

.PHONY: all debug clean

all:
	mkdir -p lib
	$(CC) $(CFLAGS) src/*.c $(LDFLAGS) -o $(LIBRARY)

# writes [KROSSHAIR] lines to /tmp/sourceyaw-overlay.log
debug:
	mkdir -p lib
	$(CC) $(filter-out -O2 -DNDEBUG,$(CFLAGS)) -ggdb src/*.c $(LDFLAGS) -o $(LIBRARY)

clean:
	rm -rf lib
