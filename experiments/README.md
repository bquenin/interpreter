# UI Framework Experiments

This folder contains minimal prototypes for evaluating Python UI frameworks for the Interpreter application.

## Quick Start

```bash
# Install experiment dependencies
pip install -r experiments/requirements.txt

# Run each prototype from the project root:
python -m experiments.pyside6.main
python -m experiments.customtkinter.main
python -m experiments.wxpython.main
python -m experiments.dearpygui.main
```

## Frameworks Tested

| Framework | Version | License |
|-----------|---------|---------|
| PySide6 (Qt) | 6.6+ | LGPL |
| CustomTkinter | 5.2+ | MIT |
| wxPython | 4.2+ | wxWindows (LGPL-like) |
| Dear PyGui | 1.10+ | MIT |

## Evaluation Criteria

Each prototype tests:
1. **Settings GUI** - Window selector, controls, status display
2. **Overlay (Banner)** - Bottom-of-screen subtitle bar, draggable
3. **Overlay (Inplace)** - Transparent, click-through, stays on top
4. **Capture Integration** - Uses existing `src/interpreter/capture/` module
5. **System Tray** - Background operation with tray icon

## Results

### PySide6 (Qt)

| Feature | macOS | Windows | Linux | Notes |
|---------|-------|---------|-------|-------|
| Settings GUI | | | | Professional look, rich widgets |
| System Tray | | | | Native support |
| Banner Overlay | | | | Works well |
| Inplace Transparent | | | | `WA_TranslucentBackground` |
| Click-through | | | | `WindowTransparentForInput` |
| Stay on Top | | | | `WindowStaysOnTopHint` |

**Pros:**
- Most mature framework (25+ years)
- Excellent documentation
- Rich widget set
- Native look on all platforms
- Good system tray support
- Transparent/click-through overlay support

**Cons:**
- Large dependency (~100MB)
- Slight learning curve

---

### CustomTkinter

| Feature | macOS | Windows | Linux | Notes |
|---------|-------|---------|-------|-------|
| Settings GUI | | | | Modern look on top of tkinter |
| System Tray | | | | Not built-in (needs pystray) |
| Banner Overlay | | | | Uses existing tkinter approach |
| Inplace Transparent | | | | Platform-specific |
| Click-through | | | | Requires extra work |
| Stay on Top | | | | `topmost` attribute |

**Pros:**
- Easy migration (already using tkinter)
- Modern appearance
- Lightweight
- No licensing concerns (MIT)

**Cons:**
- No system tray (need separate library)
- Overlay transparency is platform-specific
- Limited compared to Qt

---

### wxPython

| Feature | macOS | Windows | Linux | Notes |
|---------|-------|---------|-------|-------|
| Settings GUI | | | | Native OS look |
| System Tray | | | | `wx.adv.TaskBarIcon` |
| Banner Overlay | | | | Works |
| Inplace Transparent | | | | `SetTransparent()` |
| Click-through | | | | Limited support |
| Stay on Top | | | | `STAY_ON_TOP` style |

**Pros:**
- Native look on each platform
- System tray support
- Established library

**Cons:**
- Transparency can be tricky
- Click-through not well supported
- Less popular (sparser documentation)

---

### Dear PyGui

| Feature | macOS | Windows | Linux | Notes |
|---------|-------|---------|-------|-------|
| Settings GUI | | | | GPU-accelerated, immediate mode |
| System Tray | | | | Not supported |
| Banner Overlay | | | | Window within viewport only |
| Inplace Transparent | | | | **Not possible** |
| Click-through | | | | **Not possible** |
| Stay on Top | | | | N/A |

**Pros:**
- Very fast (GPU rendering)
- Good for real-time displays
- Modern API

**Cons:**
- **Cannot create transparent windows**
- **Cannot do click-through**
- No system tray
- Not suitable for overlay use case

---

## Recommendation

Based on the requirements (settings GUI + transparent/click-through overlay + system tray):

### 1st Choice: PySide6 (Qt)
Best overall support for all features. The large dependency size is acceptable given the existing model dependencies.

### 2nd Choice: CustomTkinter + pystray
Easier migration path. Would need `pystray` for system tray and careful platform-specific code for overlay transparency.

### Not Recommended: Dear PyGui
Cannot create transparent/click-through windows. Would require a hybrid approach (DPG for settings, Qt/tkinter for overlay).

## Testing Checklist

For each framework, verify:

- [ ] App launches without errors
- [ ] Window list populates
- [ ] Capture starts/stops
- [ ] Preview updates in real-time
- [ ] FPS counter updates
- [ ] Banner overlay appears at bottom
- [ ] Banner overlay is draggable
- [ ] Inplace overlay is transparent
- [ ] Inplace overlay is click-through (can click game underneath)
- [ ] Inplace overlay stays on top
- [ ] System tray icon appears
- [ ] Tray menu works
- [ ] App minimizes to tray on close
