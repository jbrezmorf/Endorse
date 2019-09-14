"""
This file contains algorithms for
1. constructing a 3D geometry in the BREP format
   (see https://docs.google.com/document/d/1qWq1XKfHTD-xz8vpINxpfQh4k6l1upeqJNjTJxeeOwU/edit#)
   from the Layer File format (see geometry_structures.py).
2. meshing the 3D geometry (e.g. using GMSH)
3. setting regions to the elements of the resulting mesh and other mesh postprocessing


TODO:
- check how GMSH number surfaces standing alone,
  seems that it number object per dimension by the IN time in DFS from solids down to Vtx,
  just ignoring main compound, not sure how numbering works for free standing surfaces.

- finish usage of polygon decomposition (without split)
- implement intersection in interface_finish_init
- tests

Heterogeneous mesh step:

- storing mesh step from regions into shape info objects
- ( brep created )
-
- add include


"""
import os
import numpy as np
import gmsh_io
import brep_writer as bw
from geomop import  polygons

class ShapeInfo:
    # count_by_dim = [0,0,0,0]
    """
    Class to capture information about individual shapes finally meshed by GMSH as independent objects.
    """

    _shapes_dim ={'Vertex': 0, 'Edge': 1, 'Face': 2, 'Solid': 3}

    def __init__(self, shape, reg=None):
        self.shape = shape
        if reg is None or reg.id==0:
            self.free = False
            self.i_reg = 0
        else:
            self.free = True
            self.i_reg = reg.id

    def dim(self):
        return self._shapes_dim.get(type(self.shape).__name__, None)



class Geometry2d:

    el_type_to_dim = {15: 0, 1: 1, 2: 2, 4: 3}

    """
        - create BREP B-spline approximation from Z-grids (Bapprox)
        - load other surfaces
        - create BREP geometry from it (JB)

        - write BREP geometry into a file (JE)
        - visualize BREP geometry or part of it
        - call GMSH to create the mesh (JB)
        //- convert mesh into GMSH file format from Netgen
        - name physical groups (JB)
        - scale the mesh nodes verticaly to fit original interfaces (JB, Jakub)
        - find rivers and assign given regions to corresponding elements (JB, Jakub)
    """
    def __init__(self, basename, regions):
        self.regions = regions
        self.basename = basename
        self.all_shapes = []
        self.max_step = 0.0
        self.min_step = np.inf
        self.plane_surface = None
        self.shift_to_uv = None
        self.mat_to_uv = None

    def make_plane(self, points):
        min_xy = np.array([np.inf, np.inf])
        max_xy = -min_xy
        for pt in points:
            min_xy = np.minimum(min_xy, pt)
            max_xy = np.maximum(max_xy, pt)
        self.plane_surface, corners = bw.Approx.plane([
            [min_xy[0], min_xy[1], 0.0],
            [max_xy[0], min_xy[1], 0.0],
            [min_xy[0], max_xy[1], 0.0]
        ])
        self.shift_to_uv = - np.array(min_xy[0], min_xy[1])
        diff = max_xy - min_xy
        mat = np.array([
                [diff[0], 0],
                [0, diff[1]]
        ])
        self.mat_to_uv = np.linalg.inv(mat)


    def add_compoud(self, decomp):
        """
        Make dictionaries of shapes for points, segments, polygons in common decomposition.
        :return:
        """
        vertices = {
            id: ShapeInfo(
                bw.Vertex([node.xy[0], node.xy[1], 0.0]),
                reg=node.attr
            )
            for id, node in decomp.points.items()
        }
        if self.plane_surface is None:
            self.make_plane([pt.xy for pt in decomp.points.values()])



        edges = {}
        for id, segment in decomp.segments.items():
            edge = bw.Edge([vertices[pt.id].shape for pt in segment.vtxs])
            vtxs = [pt.xy for pt in segment.vtxs]
            uv_points = [self.mat_to_uv @ (v + self.shift_to_uv) for v in vtxs]
            vtxs_xyz=[(v[0], v[1], 0.0) for v in vtxs]
            curve_uv = bw.Approx.line_2d(uv_points)
            curve_xyz = bw.Approx.line_3d(vtxs_xyz)
            edge.attach_to_2d_curve((0.0, 1.0), curve_uv, self.plane_surface)
            edge.attach_to_3d_curve((0.0, 1.0), curve_xyz)
            edges[id] = ShapeInfo(edge, reg=segment.attr)


        faces = {}
        for id, poly in decomp.polygons.items():
            if poly.is_outer_polygon():
                continue
            #segment_ids, surface_id = poly      # segment_id > n_segments .. reversed edge
            wires = [self._make_bw_wire(edges, poly.outer_wire)]
            for hole in poly.outer_wire.childs:
                wires.append(self._make_bw_wire(edges, hole).m())
            face = bw.Face(wires, surface=self.plane_surface)
            faces[id] = ShapeInfo(face, reg=poly.attr)
        self.all_shapes.extend(vertices.values())
        self.all_shapes.extend(edges.values())
        self.all_shapes.extend(faces.values())


    @staticmethod
    def _make_bw_wire(edges, decomp_wire):
        """
        Make shape Wire from decomposition wire.
        """
        wire_edges = []
        for seg, side in decomp_wire.segments():
            reversed = (side == polygons.right_side)
            ori = [bw.Orient.Reversed, bw.Orient.Forward][reversed]
            shape_ref = bw.ShapeRef(edges[seg.id].shape, orient=ori)
            wire_edges.append(shape_ref)
        return bw.Wire(wire_edges)


    def make_brep_geometry(self):
        self.free_shapes = [shp_info for shp_info in self.all_shapes if shp_info.free]
        # sort down from solids to vertices
        self.free_shapes.sort(key=lambda shp: shp.dim(), reverse=True)
        free_shapes = [shp_info.shape for shp_info in self.free_shapes]

        compound = bw.Compound(free_shapes)
        compound.set_free_shapes()
        self.brep_file = os.path.abspath(self.basename + ".brep")
        with open(self.brep_file, 'w') as f:
            bw.write_model(f, compound, bw.Location())

        self.make_gmsh_shape_dict()

    def make_gmsh_shape_dict(self):
        """
        Construct a dictionary self.gmsh_shape_dict, mapping the pair (dim, gmsh_object_id) -> shape info object
        :return:
        """
        # ignore shapes without ID - not part of the output
        output_shapes = [si for si in self.all_shapes if hasattr(si.shape, 'id')]

        # prepare dict: (dim, shape_id) : shape info
        output_shapes.sort(key=lambda si: si.shape.id, reverse=True)
        shape_by_dim = [[] for i in range(4)]
        for shp_info in output_shapes:
            dim = shp_info.dim()
            shape_by_dim[dim].append(shp_info)

        self.gmsh_shape_dist = {}
        for dim, shp_list in enumerate(shape_by_dim):
            for gmsh_shp_id, si in enumerate(shp_list):
                self.gmsh_shape_dist[(dim, gmsh_shp_id + 1)] = si

    def set_free_si_mesh_step(self, si, step):
        """
        Set the mesh step to the free SI (root of local DFS tree).
        :param si: A free shape info object
        :param step: Meash step from corresponding region.
        :return:
        """
        if step <= 0.0:
            step = self.global_mesh_step
        self.min_step = min(self.min_step, step)
        self.max_step = max(self.max_step, step)
        si.mesh_step = step

    def distribute_mesh_step(self):
        """
        For every free shape:
         1. get the mesh step from the region
         2. pass down through its tree using DFS
         3. set the mesh_step  to all child vertices, take minimum of exisiting and new mesh_step
        :return:
        """
        print("distribute mesh\n")
        self.compute_bounding_box()
        self.global_mesh_step = self.mesh_step_estimate()

        # prepare map from shapes to their shape info objs
        # initialize mesh_step of individual shape infos
        shape_dict = {}
        for shp_info in self.all_shapes:
            shape_dict[shp_info.shape] = shp_info
            shp_info.mesh_step = np.inf
            shp_info.visited = -1

        # Propagate mesh_step from the free_shapes to vertices via DFS
        # use global mesh step if the local mesh_step is zero.

        # # Distribute from lower shape dimensions.
        # def get_dim(shape_info):
        #     return self.regions[shape_info.i_reg].dim
        # self.free_shapes.sort(key=get_dim)

        for i_free, shp_info in enumerate(self.free_shapes):
            self.set_free_si_mesh_step(shp_info, self.regions[shp_info.i_reg].mesh_step)
            shape_dict[shp_info.shape].visited = i_free
            stack = [shp_info.shape]
            while stack:

                shp = stack.pop(-1)
                print("shp: {} id: {}\n".format(type(shp), shp.id))
                for sub in shp.subshapes():
                    if isinstance(sub, (bw.Vertex, bw.Edge, bw.Face, bw.Solid)):
                        if shape_dict[sub].visited < i_free:
                            shape_dict[sub].visited = i_free
                            stack.append(sub)
                    else:

                        stack.append(sub)
                if isinstance(shp, bw.Vertex):
                    shape_dict[shp].mesh_step = min(shape_dict[shp].mesh_step, shp_info.mesh_step)

        #self.min_step *= 0.2
        self.vtx_char_length = []
        for (dim, gmsh_shp_id), si in self.gmsh_shape_dist.items():
            if dim == 0:
                mesh_step = si.mesh_step
                if mesh_step == np.inf:
                    mesh_step = self.global_mesh_step
                self.vtx_char_length.append((gmsh_shp_id, mesh_step))



            # debug listing
            # xx=[ (k, v.shape.id) for k, v in self.shape_dict.items()]
            # xx.sort(key=lambda x: x[0])
            # for i in xx:
            #    print(i[0][0], i[0][1], i[1])


    def compute_bounding_box(self):
        min_vtx = np.ones(3) * (np.inf)
        max_vtx = np.ones(3) * (-np.inf)
        assert len(self.all_shapes) > 0, "Empty list of shapes to mesh."
        for si in self.all_shapes:
            if hasattr(si.shape, 'point'):
                min_vtx = np.minimum(min_vtx, si.shape.point)
                max_vtx = np.maximum(max_vtx, si.shape.point)
        assert np.all(min_vtx < np.inf)
        assert np.all(max_vtx > -np.inf)
        self.aabb = [ min_vtx, max_vtx ]


    def mesh_step_estimate(self):
        char_length = np.max(self.aabb[1] - self.aabb[0])
        mesh_step = char_length / 20
        print("Char length: {} mesh step: {}", char_length, mesh_step)
        return mesh_step


    def call_gmsh(self, gmsh_path, step_range):
        """

        :param mesh_step:
        :return:

        """
        self.distribute_mesh_step()
        self.geo_file = self.basename + ".tmp.geo"
        with open(self.geo_file, "w") as f:
            print(r'SetFactory("OpenCASCADE");', file=f)
            # print(r'Mesh.Algorithm = 2;', file=f)
            """
            TODO: GUI interface for algorithm selection and element optimizaion.
            Related options:
            Mesh.Algorithm
            2D mesh algorithm (1=MeshAdapt, 2=Automatic, 5=Delaunay, 6=Frontal, 7=BAMG, 8=DelQuad)

            Mesh.Algorithm3D
            3D mesh algorithm (1=Delaunay, 2=New Delaunay, 4=Frontal, 5=Frontal Delaunay, 6=Frontal Hex, 7=MMG3D, 9=R-tree)
            """
            """
            TODO: ? Meaning of char length limits. Possibly to prevent to small elements at intersection points,
            they must be derived from min and max mesh step.
            """
            h_min, h_max = step_range
            print(r'Mesh.CharacteristicLengthMin = %s;'% h_min, file=f)
            print(r'Mesh.CharacteristicLengthMax = %s;'% h_max, file=f)
            # rand_factor has to be increased when the triangle/model ratio
            # multiplied by rand_factor approaches 'machine accuracy'
            rand_factor = 1e-14 * np.max(self.aabb[1] - self.aabb[0]) / h_min
            print(r'Mesh.RandomFactor = %s;'%rand_factor , file=f)
            print(r'ShapeFromFile("%s")' % self.brep_file, file=f)

            for id, char_length in self.vtx_char_length:
                print(r'Characteristic Length {%s} = %s;' % (id, char_length), file=f)

        from subprocess import call
        if not os.path.exists(gmsh_path):
            gmsh_path = "gmsh"
        #call([gmsh_path, "-3", "-rand 1e-10", self.geo_file])
        call([gmsh_path, "-2", "-format", "msh2", self.geo_file])
        self.tmp_msh_file = self.basename + ".tmp.msh"
        return self.tmp_msh_file


    def modify_mesh(self):
        self.mesh = gmsh_io.GmshIO()
        with open(self.tmp_msh_file, "r") as f:
            self.mesh.read(f)

        new_elements = {}
        for id, elm in self.mesh.elements.items():
            el_type, tags, nodes = elm
            if len(tags) < 2:
                raise Exception("Less then 2 tags.")
            dim = self.el_type_to_dim[el_type]
            shape_id = tags[1]
            shape_info = self.gmsh_shape_dist[ (dim, shape_id)]

            if not shape_info.free:
                continue
            region = self.regions[shape_info.i_reg]
            if not region.is_active(dim):
                continue
            assert region.dim == dim
            physical_id = shape_info.i_reg + 10000
            if region.name in self.mesh.physical:
                assert self.mesh.physical[region.name][0] == physical_id
            else:
                self.mesh.physical[region.name] = (physical_id, dim)
            tags[0] = physical_id
            new_elements[id] = (el_type, tags, nodes)
        self.mesh.elements = new_elements
        self.msh_file = self.basename + ".msh"
        with open(self.msh_file, "w") as f:
            self.mesh.write_ascii(f)
        return self.mesh








# def make_geometry(**kwargs):
#     """
#     Read geometry from file or use provided gs.LayerGeometry object.
#     Construct the BREP geometry, call gmsh, postprocess mesh.
#     Write: geo file, brep file, tmp.msh file, msh file
#     """
#     raw_geometry = kwargs.get("geometry", None)
#     layers_file = kwargs.get("layers_file")
#     mesh_step = kwargs.get("mesh_step", 0.0)
#     mesh_file = kwargs.get("mesh_file", None)
#
#     if raw_geometry is None:
#         raw_geometry = layers_io.read_geometry(layers_file)
#     filename_base = os.path.splitext(layers_file)[0]
#
#     lg = Geometry2d(decompositions)
#
#     lg.construct_brep_geometry()
#     lg.make_gmsh_shape_dict()
#     lg.distribute_mesh_step()
#     lg.call_gmsh(mesh_step)
#     return lg.modify_mesh()


#
# if __name__ == "__main__":
#     import argparse
#
#     parser = argparse.ArgumentParser()
#     parser.add_argument('layers_file', help="Input Layers file (JSON).")
#     parser.add_argument("--mesh-step", type=float, default=0.0, help="Maximal global mesh step.")
#     args = parser.parse_args()
#
#     make_geometry(layers_file=args.layers_file, mesh_step=args.mesh_step)
