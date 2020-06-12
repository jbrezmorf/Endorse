# Description

This directory contains experimental code for MLMC applied to fractured porous media in 2d.
It is independent of the MLMC library, but some pieces of code are taken from there.
Goal is to verify the approach, where small fractures are replaced by an anisotropic random field for the bulk conductivity.
In order to apply MLMC this replacemen should result in the velocity field with the same mean value, i.e.

E( P_l(v_{l-1}) - v_l ) = 0

where P_l is projection of the velocity field from the fine level mesh to the coarse level mesh. This is done through the per element problems.

## 2019 existing plots
meshes for square 1000 x 1000, element size of coarse about 100.  

angle_ecdf.pdf          Empirical CDF for angle of the maximal eigen value for tensors with eigen value ratio 2 and greter. Seems to be isotropic.
correlations.pdf        Empirical variograms for individual conductivity tensor components. Seems that samples are uncorellated at the element scale (h - 5h).
homogenity.pdf          Plot average of tensor components over X and over Y axes. Pure test but absolutely no reason for inhomogenity. 
isotropy_alt.pdf        Plot log(|C @ u|) for unit vector 'u' of varing angle; C is conductivity tensor.
                        Changes of lower bound of order 1e-10, that is matrix conductivity. Seems that there is some preferece of directions even without fractures. 
                        Try to do the same without fractures.
isotropy.pdf            Changes of maximal and minimal eigen value with angle (rotation angle of the tensor). Strong directionality.
                        Changes of |Cmean @ unit vector|
                        Sometimes the conductivity is even smaller then backgroung conductivity.
QQ_conductivity.pdf

## Problems
  
  
- effective tensor from boundary fluxes 
  Which direction assign to the flux from fracture boundary?
- effective tensor from bulk fluxes
  The volume averaging may be inapropriate, diminishing impact of the fractures.
  
  
## Postponed Problems
- Fracture adding problem for coarse_fine mesh. PolygonDecomposition.merge_points moves the points, to average. But one of the points can be on boundary and can not move.
  Quick resolution: decrease tolerance and ignore such errors.
  Later make specific unit tests, introduce a 'move_weight' for points and segments.


## 2020 TODO:
- Flow extremly slow, about 1.5 min. per timestep takes 15 minutes to compute problem on fine mesh, 85% taken by assembly. Should not be because of the FieldFormula as it is only on the boundary.
  Seems there is a lot of allocations

- modify to be based on bgem and have own MLMC algorithm

- Possible problem with geometry_2d, Warnning when reading the BREP: 
  Warning : Something wrong in edge loop of size=17, no sign! 
  See: https://github.com/feelpp/debian-gmsh/blob/master/Geo/GEdgeLoop.cpp
  the method nextOne should return 1 or -1 sign, but it returns 0 if the wire can not be prolonged. We must review the prolongation algorithm 
  Try tu gess which wire is responsible for that.

### Properties of the projected coarse conductivity field:

**better check of isotropy**
- isotrpoy of invariants
- random rotation before decomposition
- do same plot for randomly generated eigen values

** covariance matrix for eigen valeus or invariants**
- statistic for the conductivity invariants: trace, determinant