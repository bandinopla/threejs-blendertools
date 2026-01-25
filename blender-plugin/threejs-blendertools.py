bl_info = {
    "name": "Threejs Blendertools",
    "author": "Bandinopla + Claude",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Threejs Blendertools",
    "description": "Stream object data via WebSocket",
    "category": "System",
}

import bpy
import json
import math
import socket
import threading
import struct
import hashlib
import base64
from bpy.app.handlers import persistent

# Global state
server_socket = None
client_sockets = []
is_running = False
server_thread = None
lock = threading.Lock()


def get_object_data():
    """Extract object position, rotation, and FOV (if camera)"""
    scene = bpy.context.scene
    
    # Get the selected object from scene property
    obj_name = scene.ws_selected_object
    if not obj_name or obj_name not in bpy.data.objects:
        return {
            "scrubFrame": scene.frame_current,
            "fps": scene.render.fps
        }
    
    obj = bpy.data.objects[obj_name]
    
    # Get object matrix
    mat = obj.matrix_world
    
    # Position: Blender (Z-up, -Y forward) to Three.js (Y-up, -Z forward)
    pos = mat.to_translation()
    
    # Convert Blender orientation to Three.js orientation
    import mathutils
    
    # Create conversion quaternion (rotate -90° around X)
    conversion_quat = mathutils.Quaternion((1, 0, 0), math.radians(-90))
    
    # Get Blender object quaternion and apply conversion
    blender_quat = mat.to_quaternion()
    threejs_quat = blender_quat @ conversion_quat
    
    # Get Euler angles from converted quaternion
    rot = threejs_quat.to_euler('XYZ')
    
    # Field of View (only for cameras)
    fov = None
    if obj.type == 'CAMERA':
        cam_data = obj.data
        if cam_data.type == 'PERSP':
            fov = math.degrees(cam_data.angle)
            # If angle_x is set, we need to convert to vertical FOV
            if cam_data.sensor_fit == 'HORIZONTAL' or cam_data.sensor_fit == 'AUTO':
                aspect = scene.render.resolution_x / scene.render.resolution_y
                fov_vertical = 2 * math.atan(math.tan(cam_data.angle / 2) / aspect)
                fov = math.degrees(fov_vertical)
    
    return {
        # Position: Blender Z-up to Three.js Y-up
        "position": {"x": pos.x, "y": pos.z, "z": -pos.y},
        
        # Quaternion with proper orientation conversion
        "quaternion": {
            "x": threejs_quat.x, 
            "y": threejs_quat.z, 
            "z": -threejs_quat.y, 
            "w": threejs_quat.w
        },
        
        # Euler angles in radians
        "rotation": {"x": rot.x, "y": rot.z, "z": -rot.y},
        
        "fov": fov,
        "frame": scene.frame_current,
        "fps": scene.render.fps,
        "objectName": obj_name,
        "objectType": obj.type
    }


def create_websocket_frame(data):
    """Create a WebSocket text frame"""
    message = data.encode('utf-8')
    length = len(message)
    
    frame = bytearray()
    frame.append(0x81)  # Text frame, FIN bit set
    
    if length <= 125:
        frame.append(length)
    elif length <= 65535:
        frame.append(126)
        frame.extend(struct.pack('>H', length))
    else:
        frame.append(127)
        frame.extend(struct.pack('>Q', length))
    
    frame.extend(message)
    return bytes(frame)


def parse_websocket_handshake(data):
    """Parse WebSocket handshake request"""
    headers = {}
    lines = data.decode('utf-8').split('\r\n')
    
    for line in lines[1:]:
        if ':' in line:
            key, value = line.split(':', 1)
            headers[key.strip()] = value.strip()
    
    return headers


def create_handshake_response(key):
    """Create WebSocket handshake response"""
    magic = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
    accept = base64.b64encode(
        hashlib.sha1((key + magic).encode()).digest()
    ).decode()
    
    response = (
        'HTTP/1.1 101 Switching Protocols\r\n'
        'Upgrade: websocket\r\n'
        'Connection: Upgrade\r\n'
        f'Sec-WebSocket-Accept: {accept}\r\n'
        '\r\n'
    )
    return response.encode()


def handle_client(client_socket, addr):
    """Handle individual WebSocket client"""
    global client_sockets
    
    try:
        # Receive handshake
        data = client_socket.recv(1024)
        headers = parse_websocket_handshake(data)
        
        if 'Sec-WebSocket-Key' in headers:
            # Send handshake response
            response = create_handshake_response(headers['Sec-WebSocket-Key'])
            client_socket.send(response)
            
            with lock:
                client_sockets.append(client_socket)
            print(f"WebSocket client connected from {addr}")
            
            # Keep connection alive
            while is_running:
                try:
                    client_socket.settimeout(1.0)
                    client_socket.recv(1024)
                except socket.timeout:
                    continue
                except:
                    break
    except Exception as e:
        print(f"Client error: {e}")
    finally:
        with lock:
            if client_socket in client_sockets:
                client_sockets.remove(client_socket)
        try:
            client_socket.close()
        except:
            pass
        print(f"Client {addr} disconnected")


def broadcast_data(data):
    """Send data to all connected clients"""
    message = json.dumps(data)
    frame = create_websocket_frame(message)
    
    with lock:
        disconnected = []
        for client in client_sockets:
            try:
                client.send(frame)
            except:
                disconnected.append(client)
        
        # Remove disconnected clients
        for client in disconnected:
            client_sockets.remove(client)
            try:
                client.close()
            except:
                pass


def server_loop():
    """Main server loop"""
    global server_socket, is_running
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind(('localhost', 8765))
        server_socket.listen(5)
        server_socket.settimeout(1.0)
        print("WebSocket server listening on ws://localhost:8765")
        
        while is_running:
            try:
                client_socket, addr = server_socket.accept()
                client_thread = threading.Thread(
                    target=handle_client,
                    args=(client_socket, addr),
                    daemon=True
                )
                client_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if is_running:
                    print(f"Server error: {e}")
                break
    finally:
        if server_socket:
            server_socket.close()
        print("Server stopped")


def get_object_items(self, context):
    """Generate list of objects for dropdown"""
    items = []
    for obj in bpy.data.objects:
        items.append((obj.name, obj.name, f"{obj.type}: {obj.name}"))
    
    if not items:
        items.append(("NONE", "No Objects", "No objects in scene"))
    
    return items


class OBJECT_WS_OT_start(bpy.types.Operator):
    """Start WebSocket server and streaming"""
    bl_idname = "object_ws.start"
    bl_label = "Start Server"
    
    _timer = None
    _last_fps = None
    
    def modal(self, context, event):
        global is_running
        
        if event.type == 'TIMER' and is_running:
            # Check if FPS changed and update timer if needed
            current_fps = context.scene.render.fps
            if self._last_fps != current_fps:
                self._last_fps = current_fps
                # Remove old timer
                wm = context.window_manager
                wm.event_timer_remove(self._timer)
                # Add new timer with updated FPS
                self._timer = wm.event_timer_add(1.0 / current_fps, window=context.window)
            
            # Update and broadcast object data
            data = get_object_data()
            if data and client_sockets:
                broadcast_data(data)
            return {'PASS_THROUGH'}
        
        if not is_running:
            self.cancel(context)
            return {'CANCELLED'}
        
        return {'PASS_THROUGH'}
    
    def execute(self, context):
        global is_running, server_thread, client_sockets
        
        if is_running:
            self.report({'WARNING'}, "Server already running")
            return {'CANCELLED'}
        
        if not context.scene.ws_selected_object:
            self.report({'ERROR'}, "No object selected")
            return {'CANCELLED'}
        
        is_running = True
        client_sockets.clear()
        
        # Start server thread
        server_thread = threading.Thread(target=server_loop, daemon=True)
        server_thread.start()
        
        # Setup modal timer
        wm = context.window_manager
        fps = context.scene.render.fps
        self._last_fps = fps
        self._timer = wm.event_timer_add(1.0 / fps, window=context.window)
        wm.modal_handler_add(self)
        
        self.report({'INFO'}, "WebSocket server started on ws://localhost:8765")
        return {'RUNNING_MODAL'}
    
    def cancel(self, context):
        if self._timer:
            wm = context.window_manager
            wm.event_timer_remove(self._timer)


class OBJECT_WS_OT_stop(bpy.types.Operator):
    """Stop WebSocket server"""
    bl_idname = "object_ws.stop"
    bl_label = "Stop Server"
    
    def execute(self, context):
        global is_running, server_socket, client_sockets
        
        if not is_running:
            self.report({'WARNING'}, "Server not running")
            return {'CANCELLED'}
        
        is_running = False
        
        # Close all client connections
        with lock:
            for client in client_sockets:
                try:
                    client.close()
                except:
                    pass
            client_sockets.clear()
        
        # Close server socket
        if server_socket:
            try:
                server_socket.close()
            except:
                pass
        
        self.report({'INFO'}, "WebSocket server stopped")
        return {'FINISHED'}


class OBJECT_WS_OT_pick_object(bpy.types.Operator):
    """Pick currently selected object"""
    bl_idname = "object_ws.pick_object"
    bl_label = "Pick Selected Object"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        if context.active_object:
            context.scene.ws_selected_object = context.active_object.name
            self.report({'INFO'}, f"Selected: {context.active_object.name}")
            
            # Force UI refresh
            for area in context.screen.areas:
                area.tag_redraw()
        else:
            self.report({'WARNING'}, "No active object")
        return {'FINISHED'}


class OBJECT_WS_PT_panel(bpy.types.Panel):
    """Panel in the 3D viewport sidebar"""
    bl_label = "ThreeJs Tools"
    bl_idname = "OBJECT_WS_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ThreeJs Tools'
    
    def draw(self, context):
        layout = self.layout
        
        col = layout.column(align=True)
        
        # Object selector with picker
        col.label(text="Select Object:")
        row = col.row(align=True)
        row.prop_search(context.scene, "ws_selected_object", bpy.data, "objects", text="")
        row.operator("object_ws.pick_object", text="", icon='PIVOT_CURSOR')
        
        # Show selected object info
        if context.scene.ws_selected_object:
            obj = bpy.data.objects.get(context.scene.ws_selected_object)
            if obj:
                col.label(text=f"Type: {obj.type}")
            else:
                col.label(text="Object not found", icon='ERROR')
        else:
            col.label(text="No object selected", icon='ERROR')
        
        col.separator()
        
        # Show FPS (updates dynamically)
        col.label(text=f"FPS: {context.scene.render.fps}")
        
        # Show connected clients
        with lock:
            col.label(text=f"Clients: {len(client_sockets)}")
        
        col.separator()
        
        # Start/Stop buttons
        global is_running
        if is_running:
            col.operator("object_ws.stop", icon='SNAP_FACE')
            col.label(text="Status: Running", icon='PLAY')
            col.label(text="ws://localhost:8765")
        else:
            col.operator("object_ws.start", icon='PLAY')
            col.label(text="Status: Stopped", icon='PAUSE')


classes = (
    OBJECT_WS_OT_start,
    OBJECT_WS_OT_stop,
    OBJECT_WS_OT_pick_object,
    OBJECT_WS_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Register scene property for object selection
    bpy.types.Scene.ws_selected_object = bpy.props.StringProperty(
        name="Selected Object",
        description="Object to stream via WebSocket",
        default=""
    )


def unregister():
    global is_running
    is_running = False
    
    # Unregister scene property
    del bpy.types.Scene.ws_selected_object
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()