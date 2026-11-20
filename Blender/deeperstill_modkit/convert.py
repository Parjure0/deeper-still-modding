"""Frames: Blender <-> game units <-> level JSON of the game.

- Blender scene: 1 unit = 1 cm (unit scale 0.01), Z up, right-handed.
  Game frame = (X, -Y, Z) of Blender (cm, Z up, left-handed).
- Level JSON of the game: metres, Y up; position = (X, Z, Y) of the game frame / 100,
  rotation as a quaternion [x, y, z, w].

The origin of an NPC or player start in Blender is at its feet (bottom of
the capsule); the game actor is at the centre of the capsule.
"""

import math

from mathutils import Matrix, Quaternion, Vector

M = Matrix.Diagonal((1.0, -1.0, 1.0))                               # Blender <-> game frame
P = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)))   # game frame <-> level JSON


def blender_from_level(t, r):
    """(Blender position in cm, Blender rotation matrix) from t / r of the level JSON."""
    ue = Vector((t[0], t[2], t[1])) * 100.0
    rot_json = Quaternion((r[3], r[0], r[1], r[2])).to_matrix()
    rot_b = M @ (P @ rot_json @ P) @ M
    return Vector((ue.x, -ue.y, ue.z)), rot_b


def blender_matrix_from_level(t, r, s=(1.0, 1.0, 1.0)):
    loc, rot = blender_from_level(t, r)
    return Matrix.Translation(loc) @ rot.to_4x4() @ Matrix.Diagonal((s[0], s[2], s[1], 1.0))


def game_from_blender(loc, rot_b):
    return Vector((loc.x, -loc.y, loc.z)), M @ rot_b @ M


def rotator(rot_ue):
    """Game rotator (degrees) of a game-frame rotation matrix."""
    e = rot_ue.to_euler("XYZ")
    c = lambda a: round(math.degrees(a), 4) + 0.0
    return {"pitch": c(-e.y), "yaw": c(e.z), "roll": c(-e.x)}


def level_transform(loc_ue, rot_ue):
    """t and r in the level JSON frame."""
    t = [loc_ue.x / 100.0, loc_ue.z / 100.0, loc_ue.y / 100.0]
    q = (P @ rot_ue @ P).to_quaternion()
    return [round(v, 6) + 0.0 for v in t], [round(v, 8) + 0.0 for v in (q.x, q.y, q.z, q.w)]


def rotation_scale(m3, signs=None):
    """Proper rotation and signed scale of a 3x3 matrix (m3 = R x diag(scale)).
    A mirrored object keeps its mirror in the scale (on the axes of `signs`,
    else X when the determinant is negative)."""
    if signs is None:
        signs = (-1.0, 1.0, 1.0) if m3.determinant() < 0.0 else (1.0, 1.0, 1.0)
    rot = (m3 @ Matrix.Diagonal(Vector(signs))).normalized()
    sc = m3.to_scale()
    return rot, Vector([abs(v) * g for v, g in zip(sc, signs)])


def signs_of(scale):
    return tuple(-1.0 if v < 0.0 else 1.0 for v in scale)


def pose_from_matrix(mw, signs=None, lift=0.0):
    """Level JSON pose (t, r, s) and game-frame location / rotation of a Blender
    matrix; `lift`: cm added along Z (feet -> capsule centre)."""
    loc = mw.translation.copy()
    loc.z += lift
    rot_b, s = rotation_scale(mw.to_3x3(), signs)
    loc_ue, rot_ue = game_from_blender(loc, rot_b)
    t, r = level_transform(loc_ue, rot_ue)
    return {"t": t, "r": r, "s": [round(s.x, 6), round(s.z, 6), round(s.y, 6)],
            "ue_location": [round(v, 4) + 0.0 for v in loc_ue], "ue_rotation": rotator(rot_ue)}


# --- Win camera -------------------------------------------------------
# Components of the game actor: CameraParentParent (0, 0, 10), pitch -30 ->
# CameraParent (-180, 0, 0) -> Camera (20, 0, 0), horizontal field of view 100°.
# In Blender, the object is the camera itself; the actor is computed from it.

WINVIEW_ARM_LOCATION = (0.0, 0.0, 10.0)
WINVIEW_ARM_PITCH = -30.0
WINVIEW_CAMERA_X = -160.0
WINVIEW_FOV = 100.0
WINVIEW_NEAR = 7.0
WINVIEW_FAR = 100000.0
# Axes of a Blender camera (X right, Y up, looking along -Z) in the Blender
# frame of an actor (X forward, Y left, Z up).
CAM_AXES = Matrix(((0.0, 0.0, -1.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))


def winview_chain():
    return (Matrix.Translation(WINVIEW_ARM_LOCATION)
            @ Matrix.Rotation(math.radians(-WINVIEW_ARM_PITCH), 4, "Y")
            @ Matrix.Translation((WINVIEW_CAMERA_X, 0.0, 0.0)))


def winview_pose(mw):
    """Level JSON pose of the win camera actor from the Blender camera matrix."""
    rot_cam, _s = rotation_scale(mw.to_3x3(), (1.0, 1.0, 1.0))
    rot_ue = M @ (rot_cam @ CAM_AXES.transposed()) @ M
    cam_ue = Matrix.Translation(M @ mw.translation) @ rot_ue.to_4x4()
    actor_ue = cam_ue @ winview_chain().inverted()
    loc_ue, rot = actor_ue.translation, actor_ue.to_3x3().normalized()
    t, r = level_transform(loc_ue, rot)
    return {"t": t, "r": r, "s": [1.0, 1.0, 1.0], "ue_location": [round(v, 4) + 0.0 for v in loc_ue],
            "ue_rotation": rotator(rot)}


def setup_win_camera(cam):
    """Camera with the game's field of view: 100° horizontally, whatever the image format."""
    cam.type = "PERSP"
    cam.sensor_fit = "HORIZONTAL"
    cam.angle_x = math.radians(WINVIEW_FOV)
    cam.clip_start = WINVIEW_NEAR
    cam.clip_end = WINVIEW_FAR
    cam.shift_x = cam.shift_y = 0.0
