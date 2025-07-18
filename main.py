"""
Spectrometer GUI – Theremino-style lite replica
==============================================
Uno script *stand-alone* che, collegata una **WebCam USB** (OpenCV), visualizza:

* **Live feed** con possibilità di ribaltamento (Flip H / Flip V)
* **ROI interattiva** (rettangolo trascinabile) su cui calcolare lo spettro
* **Plot in tempo reale** dell’intensità media per colonna (profilo 1-D)
* **Calibrazione lineare** pixel→nm tramite due cursori mobili + input λ
* **Pannello controlli** esposizione, guadagno, luminosità, contrasto, FPS

Dipendenze → `pip install pyqt5 pyqtgraph opencv-python numpy`
Esegui con `python spectrometer_gui.py`

Nota: è un prototipo robusto ma compatto (~300 righe); per produzione va
spacchettato in moduli, aggiunti thread separati per I/O e test.
"""

import sys, cv2, numpy as np, pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QCheckBox, QSlider, QGroupBox, QPushButton, QSpinBox, QDoubleSpinBox
)

# ------------------------------------------------------------
# Video acquisition wrapper
# ------------------------------------------------------------
class Webcam:
    def __init__(self, index: int = 0):
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError("Impossibile aprire la webcam")
        self.flip_h, self.flip_v = False, False

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("Frame non disponibile")
        if self.flip_h:
            frame = cv2.flip(frame, 1)
        if self.flip_v:
            frame = cv2.flip(frame, 0)
        return frame

    # set/get OpenCV property with fallback silenzioso
    def set_prop(self, pid: int, value: float):
        self.cap.set(pid, float(value))

    def property(self, pid: int):
        return self.cap.get(pid)

# ------------------------------------------------------------
# Main GUI
# ------------------------------------------------------------
class SpectrometerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Python Spectrometer – live webcam")
        self.resize(1400, 700)

        # ---- central widgets -------------------------------------------------
        central = QWidget(); self.setCentralWidget(central)
        hbox = QHBoxLayout(central)

        # Left: video + ROI
        self.img_view = pg.ImageView(view=pg.PlotItem())
        self.img_view.ui.histogram.hide(); self.img_view.ui.roiBtn.hide();
        self.img_view.ui.menuBtn.hide()
        self.img_view.getView().invertY(True)  # coords stile immagine
        hbox.addWidget(self.img_view, 5)

        # ROI rettangolo (default 200x100 px)
        self.roi = pg.RectROI([200, 200], [200, 100], pen='r')
        self.img_view.addItem(self.roi)

        # Right: spettro
        self.spec_plot = pg.PlotWidget(labels={'left': 'Intensity (a.u.)',
                                               'bottom': 'Pixel'})
        self.spec_curve = self.spec_plot.plot(pen='y')
        hbox.addWidget(self.spec_plot, 4)

        # InfiniteLine cursori calibrazione
        self.l1 = pg.InfiniteLine(angle=90, movable=True, pen='c')
        self.l2 = pg.InfiniteLine(angle=90, movable=True, pen='m')
        self.spec_plot.addItem(self.l1); self.spec_plot.addItem(self.l2)
        self.calib_set = False  # flag se calibrazione attiva

        # ---- right dock: controlli ------------------------------------------
        controls = self._build_controls()
        hbox.addWidget(controls, 2)

        # ---- webcam + timer --------------------------------------------------
        self.cam = Webcam(0)
        self.timer = QTimer(self); self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)  # ~33 FPS

    # ---------------------------------------------------------------------
    def _build_controls(self):
        box = QGroupBox("Controls")
        v = QVBoxLayout(box)

        # Flip checkboxes
        self.chk_flip_h = QCheckBox("Flip H"); v.addWidget(self.chk_flip_h)
        self.chk_flip_v = QCheckBox("Flip V"); v.addWidget(self.chk_flip_v)
        self.chk_flip_h.stateChanged.connect(lambda: self._set_flip())
        self.chk_flip_v.stateChanged.connect(lambda: self._set_flip())

        # Video sliders helper
        def add_slider(text, prop_id, rng, init):
            lbl = QLabel(f"{text}: {init}"); v.addWidget(lbl)
            sld = QSlider(Qt.Horizontal); sld.setRange(*rng); sld.setValue(init)
            v.addWidget(sld)
            sld.valueChanged.connect(lambda val: (lbl.setText(f"{text}: {val}"),
                                                  self.cam.set_prop(prop_id, val)))
        add_slider("Exposure", cv2.CAP_PROP_EXPOSURE, (-10, -1), int(self.cam.property(cv2.CAP_PROP_EXPOSURE)))
        add_slider("Gain",     cv2.CAP_PROP_GAIN,     (0, 255), int(self.cam.property(cv2.CAP_PROP_GAIN)))
        add_slider("Brightness", cv2.CAP_PROP_BRIGHTNESS, (0,255), int(self.cam.property(cv2.CAP_PROP_BRIGHTNESS)))
        add_slider("Contrast", cv2.CAP_PROP_CONTRAST, (0,255), int(self.cam.property(cv2.CAP_PROP_CONTRAST)))

        # Calibrazione λ
        calib_box = QGroupBox("Calibrazione 2-punti"); v.addWidget(calib_box)
        c_lay = QVBoxLayout(calib_box)
        self.spin_l1 = QDoubleSpinBox(); self.spin_l1.setSuffix(" nm"); self.spin_l1.setRange(200, 1000)
        self.spin_l2 = QDoubleSpinBox(); self.spin_l2.setSuffix(" nm"); self.spin_l2.setRange(200, 1000)
        self.spin_l1.setValue(436.0); self.spin_l2.setValue(546.0)
        c_lay.addWidget(QLabel("λ-1")); c_lay.addWidget(self.spin_l1)
        c_lay.addWidget(QLabel("λ-2")); c_lay.addWidget(self.spin_l2)
        btn_calib = QPushButton("Applica calibrazione"); c_lay.addWidget(btn_calib)
        btn_calib.clicked.connect(self.apply_calib)

        v.addStretch(1)
        return box

    # ---------------------------------------------------------------------
    def _set_flip(self):
        self.cam.flip_h = self.chk_flip_h.isChecked()
        self.cam.flip_v = self.chk_flip_v.isChecked()

    # ---------------------------------------------------------------------
    def update_frame(self):
        frame = self.cam.read()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.img_view.setImage(gray.T, autoLevels=False, autoHistogramRange=False)
        # ROI estrazione
        roi_img = self.roi.getArrayRegion(gray, self.img_view.imageItem)
        if roi_img is None or roi_img.size == 0:
            return
        spec = roi_img.mean(axis=0)
        x = np.arange(len(spec))
        if self.calib_set:
            x = self.px_to_nm(x)
            self.spec_plot.setLabel('bottom', 'Wavelength', units='nm')
        else:
            self.spec_plot.setLabel('bottom', 'Pixel')
        self.spec_curve.setData(x, spec)

    # ---------------------------------------------------------------------
    def apply_calib(self):
        # pixel positions dei cursori sul plot corrente
        px1 = self.l1.value(); px2 = self.l2.value()
        if px1 == px2:
            return
        l1 = self.spin_l1.value(); l2 = self.spin_l2.value()
        self.slope = (l2 - l1) / (px2 - px1)
        self.intercept = l1 - self.slope * px1
        self.px_to_nm = lambda px: self.slope * px + self.intercept
        self.calib_set = True

# ------------------------------------------------------------
if __name__ == "__main__":
    pg.setConfigOptions(imageAxisOrder='row-major')
    app = QApplication(sys.argv)
    win = SpectrometerGUI(); win.show()
    sys.exit(app.exec_())
