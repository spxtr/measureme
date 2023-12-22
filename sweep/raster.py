import numpy as np

'''
TODO:
- sweep needs some way of storing verticies within the data file
'''

def rasterize(vertices, nx, ny, fast_axis, rev_x=False, rev_y=False):
    '''
    Returns the x and y coordinates of the points inside the polygon defined
    by vertices. The points are defined by nx and ny points along the x and y
    axes, respectively.
    
    Parameters
    ----------
    vertices : ndarray
        Array of shape (n, 2) defining the vertices of the polygon.
    nx : int
        Number of points along the x axis.
    ny : int
        Number of points along the y axis.
    fast_axis : int
        0 if the x axis is the fast axis, 1 if the y axis is the fast axis.
    rev_x : bool
        If True, the x axis is reversed.
    rev_y : bool
        If True, the y axis is reversed.
    '''

    xs_mat, ys_mat = _bounding_mesh(vertices, nx, ny, fast_axis, rev_x, rev_y)
    is_raster, js_raster = _rasterized_indices(vertices, xs_mat, ys_mat)
    xs = xs_mat[is_raster, js_raster]
    ys = ys_mat[is_raster, js_raster]
    return xs, ys


def _bounding_mesh(vertices, nx, ny, fast_axis, rev_x=False, rev_y=False):
    '''
    Returns a meshgrid of points defining the bounding box of the polygon
    defined by vertices. The meshgrid is defined by nx and ny points along
    the x and y axes, respectively. 

    Parameters 
    ----------
    vertices : ndarray
        Array of shape (n, 2) defining the vertices of the polygon.
    nx : int
        Number of points along the x axis.
    ny : int
        Number of points along the y axis.
    fast_axis : int
        0 if the x axis is the fast axis, 1 if the y axis is the fast axis.
    '''

    xmin = np.min(vertices[:, 0])
    xmax = np.max(vertices[:, 0])
    ymin = np.min(vertices[:, 1])
    ymax = np.max(vertices[:, 1])

    if rev_x:
        xs = np.linspace(xmax, xmin, nx)
    else:
        xs = np.linspace(xmin, xmax, nx)

    if rev_y:
        ys = np.linspace(ymax, ymin, ny)
    else:
        ys = np.linspace(ymin, ymax, ny)

    if fast_axis == 0:
        xs_mat, ys_mat = np.meshgrid(xs, ys, indexing='xy')
    else:
        xs_mat, ys_mat = np.meshgrid(xs, ys, indexing='ij')

    return xs_mat, ys_mat


def _rasterized_indices(vertices, xs_mat, ys_mat):
    '''
    Returns the indices of the points in the meshgrid that are inside the
    polygon defined by vertices.
    '''

    is_raster = []
    js_raster = []
    for i in range(len(xs_mat)):
        for j in range(len(ys_mat)):
            inside = _point_in_polygon((xs_mat[i, j], ys_mat[i, j]), vertices)
            if inside:
                is_raster.append(i)
                js_raster.append(j)

    return is_raster, js_raster


def _point_in_polygon(point, vertices):
    '''
    Returns True if point is inside the polygon defined by vertices, False
    otherwise.
    '''

    x, y = point
    n = len(vertices)
    inside = False

    p1x, p1y = vertices[0]
    for i in range(n + 1):
        p2x, p2y = vertices[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside


def random_ngon_vertices(n):
    '''
    Returns the vertices of a random n-gon.
    '''

    angles = np.random.rand(n) * 2 * np.pi
    angles.sort()
    r = 10*np.random.rand(n)
    x = r*np.cos(angles)
    y = r*np.sin(angles)
    vertices = np.column_stack([x, y])
    return vertices


def pcolorize_data(zs, vertices, nx, ny, fast_axis, rev_x=False, rev_y=False):
    '''
    For a given data set zs for each point in the polygon defined by vertices,
    returns matricies xs_mat, ys_mat, and zs_mat that can be used to plot the
    data using plt.pcolormesh(xs_mat, ys_mat, zs_mat).
    '''

    xs_mat, ys_mat = _bounding_mesh(vertices, nx, ny, fast_axis, rev_x, rev_y)
    is_raster, js_raster = _rasterized_indices(vertices, xs_mat, ys_mat)
    zs_mat = np.full((nx, ny), np.nan)
    zs_mat[is_raster, js_raster] = zs
    return xs_mat, ys_mat, zs_mat