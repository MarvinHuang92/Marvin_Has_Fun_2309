# -*- coding: utf-8 -*-
"""Panda3D 程序化几何工具（原型用，不参与物理）。"""
import math

from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData,
                          GeomVertexFormat, GeomVertexWriter, Material, NodePath,
                          Vec3, Vec4)


def material(rgb, ambient=0.35, specular=0.08):
    mat = Material()
    mat.setDiffuse(Vec4(rgb[0], rgb[1], rgb[2], 1.0))
    mat.setAmbient(Vec4(rgb[0] * ambient, rgb[1] * ambient, rgb[2] * ambient, 1.0))
    mat.setSpecular(Vec4(specular, specular, specular, 1.0))
    mat.setShininess(12.0)
    return mat


class MeshBuilder(object):
    """把若干平面（每个面独立法线）合并成一个 Geom，减少 draw call。"""

    def __init__(self, name):
        self.name = name
        self.vertices = []
        self.normals = []
        self.triangles = []

    def add_triangle(self, p0, p1, p2, normal):
        base = len(self.vertices)
        self.vertices.extend([p0, p1, p2])
        self.normals.extend([normal, normal, normal])
        self.triangles.append((base, base + 1, base + 2))

    def add_quad(self, p0, p1, p2, p3, normal):
        self.add_triangle(p0, p1, p2, normal)
        self.add_triangle(p0, p2, p3, normal)

    def add_box(self, center, half, axes=None):
        """有朝向的长方体；axes 为 (ex, ey, ez) 三个单位轴。"""
        if axes is None:
            axes = (Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1))
        ex, ey, ez = axes
        hx, hy, hz = half
        cx, cy, cz = center
        corners = {}
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    corners[(sx, sy, sz)] = Vec3(
                        cx + ex.x * hx * sx + ey.x * hy * sy + ez.x * hz * sz,
                        cy + ex.y * hx * sx + ey.y * hy * sy + ez.y * hz * sz,
                        cz + ex.z * hx * sx + ey.z * hy * sy + ez.z * hz * sz)
        faces = (
            ((1, 0, 0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
            ((-1, 0, 0), [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]),
            ((0, 1, 0), [(-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)]),
            ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
            ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
            ((0, 0, -1), [(-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1)]),
        )
        for normal_tuple, keys in faces:
            normal = (ex * normal_tuple[0] * 1.0 + ey * normal_tuple[1] * 1.0
                      + ez * normal_tuple[2] * 1.0)
            normal.normalize()
            self.add_quad(corners[keys[0]], corners[keys[1]],
                          corners[keys[2]], corners[keys[3]], normal)

    def add_cylinder(self, center_x, center_y, z0, z1, radius, segments=12,
                     top=True):
        for index in range(segments):
            a0 = 2.0 * math.pi * index / segments
            a1 = 2.0 * math.pi * (index + 1) / segments
            p0 = Vec3(center_x + radius * math.cos(a0),
                      center_y + radius * math.sin(a0), z0)
            p1 = Vec3(center_x + radius * math.cos(a1),
                      center_y + radius * math.sin(a1), z0)
            p2 = Vec3(p1.x, p1.y, z1)
            p3 = Vec3(p0.x, p0.y, z1)
            n0 = Vec3(math.cos(a0), math.sin(a0), 0)
            n1 = Vec3(math.cos(a1), math.sin(a1), 0)
            self.add_quad(p0, p1, p2, p3, (n0 + n1).normalized())
        if top:
            center = Vec3(center_x, center_y, z1)
            for index in range(segments):
                a0 = 2.0 * math.pi * index / segments
                a1 = 2.0 * math.pi * (index + 1) / segments
                p0 = Vec3(center_x + radius * math.cos(a0),
                          center_y + radius * math.sin(a0), z1)
                p1 = Vec3(center_x + radius * math.cos(a1),
                          center_y + radius * math.sin(a1), z1)
                self.add_triangle(center, p0, p1, Vec3(0, 0, 1))

    def build(self, parent, mat, two_sided=True):
        if not self.triangles:
            return None
        vdata = GeomVertexData(self.name, GeomVertexFormat.getV3n3(),
                               Geom.UHStatic)
        vdata.setNumRows(len(self.vertices))
        vertex = GeomVertexWriter(vdata, "vertex")
        normal = GeomVertexWriter(vdata, "normal")
        for point, norm in zip(self.vertices, self.normals):
            vertex.addData3f(point)
            normal.addData3f(norm)
        prim = GeomTriangles(Geom.UHStatic)
        for a, b, c in self.triangles:
            prim.addVertices(a, b, c)
        prim.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(prim)
        node = GeomNode(self.name)
        node.addGeom(geom)
        result = NodePath(node)
        result.setMaterial(mat)
        if two_sided:
            result.setTwoSided(True)
        result.reparentTo(parent)
        return result
