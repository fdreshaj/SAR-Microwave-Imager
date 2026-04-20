import math
import matplotlib.pyplot as plt

class GridGenerator:
    def create_grid(self, anchorsx: list[float], anchorsy: list[float], targetx: float, targety: float, hqx: float, hqy: float):
        """
        Generates a 1mm grid and calculates the polar trajectory from HQ to Target.
        """
        if len(anchorsx) < 3 or len(anchorsy) < 3:
            raise ValueError("Three anchors are required.")

        # --- 1. Grid Generation Logic (Vector-Based) ---
        ox, oy = anchorsx[0], anchorsy[0] # The Origin corner
        
        # Vectors to the other two anchors (creating the sides of the grid)
        v1_x, v1_y = anchorsx[1] - ox, anchorsy[1] - oy
        v2_x, v2_y = anchorsx[2] - ox, anchorsy[2] - oy

        # Distances
        dist_1 = math.sqrt(v1_x**2 + v1_y**2)
        dist_2 = math.sqrt(v2_x**2 + v2_y**2)

        # 1mm step vectors (Normalize)
        step1_x, step1_y = v1_x / dist_1, v1_y / dist_1
        step2_x, step2_y = v2_x / dist_2, v2_y / dist_2

        num_steps1 = int(dist_1) + 1
        num_steps2 = int(dist_2) + 1

        grid = []
        all_points_flat = [] # Flat list useful for plotting

        for i in range(num_steps1):
            row = []
            for j in range(num_steps2):
                # Calculate: Origin + (i * step1_vector) + (j * step2_vector)
                px = ox + (i * step1_x) + (j * step2_x)
                py = oy + (i * step1_y) + (j * step2_y)
                
                point = (round(px, 3), round(py, 3))
                row.append(point)
                all_points_flat.append(point)
            grid.append(row)

        # --- 2. Trajectory Logic (HQ to Target, Polar in Degrees) ---
        dx = targetx - hqx
        dy = targety - hqy

        # Radius (mm)
        radius = math.sqrt(dx**2 + dy**2)

        # Angle in Degrees (0° is East, 90° is North)
        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad)

        return grid, (radius, angle_deg), all_points_flat

    def visualize(self, anchorsx, anchorsy, target, hq, grid_points_flat):
        """
        Plots the anchors, grid, HQ, Target, and the resulting vector.
        """
        plt.figure(figsize=(10, 10))
        ax = plt.gca() # Get current axes

        # 1. Plot the Grid Points (small grey dots)
        gx, gy = zip(*grid_points_flat) if grid_points_flat else ([],[])
        plt.scatter(gx, gy, color='lightgrey', s=1, label='1mm Grid')

        # 2. Plot Anchors (Large Black X's)
        # We connect them to visualize the right-angle shape
        plt.plot(anchorsx, anchorsy, 'kX-', markersize=10, label='Anchors (A0 corner)')
        for i in range(len(anchorsx)):
            plt.text(anchorsx[i], anchorsy[i], f'A{i}', fontsize=12, fontweight='bold')

        # 3. Plot HQ (Blue Circle)
        plt.plot(hq[0], hq[1], 'bo', markersize=10, label='HQ')
        
        # 4. Plot Target (Red Star)
        plt.plot(target[0], target[1], 'r*', markersize=15, label='Target')

        # 5. Plot the Trajectory Vector (Arrow from HQ to Target)
        # Using annotate makes drawing an arrow very clean
        plt.annotate('', xy=(target[0], target[1]), xytext=(hq[0], hq[1]),
                    arrowprops=dict(facecolor='blue', shrink=0.05, width=2, headwidth=8))

        # --- Plot Styling ---
        plt.title('Grid and HQ-to-Target Trajectory', fontsize=16)
        plt.xlabel('X (mm)', fontsize=12)
        plt.ylabel('Y (mm)', fontsize=12)
        
        # CRITICAL: Equal aspect ratio ensures 1mm vertical equals 1mm horizontal
        plt.axis('equal') 
        
        plt.grid(True, which='both', linestyle='--', linewidth=0.5)
        plt.legend(loc='upper right')
        
        print("Displaying plot... (Close window to continue)")
        plt.show()

# --- TEST SCRIPT ---
if __name__ == "__main__":
    gen = GridGenerator()

    # TEST CASE 1: Standard Right Angle (Aligned to Axes)
    # A0=(0,0), A1=(0,10), A2=(15,0)
    anchors_x = [0.0, 0.0, 4000]
    anchors_y = [0.0, 1000, 0.0]
    
    hq_coords = (0, 0)
    target_coords = (1200, 900)

    # TEST CASE 2: Rotated Right Angle (Uncomment to test)
    # A0=(0,0), A1=(7.07, 7.07), A2=(7.07, -7.07) (Tilted 45 degrees)
    # anchors_x = [0.0, 7.07, 7.07]
    # anchors_y = [0.0, 7.07, -7.07]
    # hq_coords = (1.0, 1.0)
    # target_coords = (10.0, 0.0)

    # 1. Generate Data
    grid, trajectory, flat_points = gen.create_grid(anchors_x, anchors_y, 
                                                   target_coords[0], target_coords[1], 
                                                   hq_coords[0], hq_coords[1])
    radius, angle = trajectory

    # 2. Print Results
    print(f"\n--- Results ---")
    print(f"Grid Dimensions: {len(grid)} rows x {len(grid[0])} columns")
    print(f"Trajectory (Polar - Degrees):")
    print(f"  > Radius: {radius:.2f} mm")
    print(f"  > Angle:  {angle:.2f}°")
    print("-" * 15)

    # 3. Visualize
    gen.visualize(anchors_x, anchors_y, target_coords, hq_coords, flat_points)