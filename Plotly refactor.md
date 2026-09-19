Please refactor my Plotly code (or generate a boilerplate script) to optimize it for handling a structural framing plan with buttery-smooth panning and zooming. The drawing needs to perform cleanly at 60 FPS like a CAD program. 

Please enforce the following technical and architectural requirements:

1. High-Performance WebGL Engine:
   - Convert all standard plotting traces to use WebGL. Use `go.Scattergl` instead of `go.Scatter` for drawing lines, beams, grids, and framing elements.

2. Data Packing Optimization:
   - Do NOT loop through structural elements to call `add_trace()` individually.
   - Batch coordinates into a single, unified list separated by `None` values to represent separate, disconnected framing members (e.g., individual beams or columns).

3. Exact Engineering Scale & Layout:
   - Configure the layout using `scaleanchor="x"` and `scaleratio=1` on the Y-axis to lock a 1:1 aspect ratio. Beams must never distort or stretch geometrically during window resizing or zooming.
   - Set the default mouse drag mode to `'pan'` (or `'zoom'`) so it behaves naturally as a floor plan viewer.
   - Implement a clean, high-contrast engineering canvas (white background, thin light-gray grid lines, disabled zero-lines).

4. Layered Text Management:
   - Separate the structural geometry lines from the member text labels (e.g., "W14x22"). 
   - Put text labels into their own isolated `go.Scattergl(mode='text')` trace so they can be easily toggled via the legend without lagging the geometric lines.

Please output clean, well-documented Python code implementing these optimizations.
