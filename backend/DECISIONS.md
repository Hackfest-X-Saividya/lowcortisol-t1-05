# Decisions log

Deviations from the prompt and choices made where the prompt was ambiguous or
where provider details had changed. Newest at the bottom.

1. **Python version.** The prompt asks for Python 3.11. The developer's laptop has
   Python 3.13 and MediaPipe 1.2.0 ships wheels for 3.9–3.14, so `requires-python`
   is `>=3.11` and the venv was created with the installed 3.13. Nothing in the
   code base uses features newer than 3.11.
2. **OpenCV distribution.** MediaPipe declares a hard dependency on
   `opencv-contrib-python`. Installing `opencv-python-headless` alongside it would
   create two competing `cv2` packages, so the project depends on MediaPipe and
   uses the `cv2` it brings. `cv2.seamlessClone`, `warpAffine`, `Subdiv2D` and
   the drawing calls used here are all in the core module.
3. **MediaPipe 1.x API.** MediaPipe 1.2.0 re-implemented the Python Tasks layer on
   ctypes, but `FaceLandmarker.create_from_options(...).detect(mp.Image)` and the
   `FaceLandmarksConnections.FACE_LANDMARKS_*` connection lists (now including a
   `NOSE` set) are unchanged, so `services/sketch/regions.py` builds its index
   groups from those lists as the prompt requires.
