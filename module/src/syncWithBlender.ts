import { PerspectiveCamera } from "three";

interface BlenderObjectData {
	position: { x: number; y: number; z: number };
	quaternion: { x: number; y: number; z: number; w: number };
	rotation: { x: number; y: number; z: number };
	fov: number | null;
	frame: number;
	fps: number;
	objectName: string;
	objectType: string;
	scrubFrame?: number;
}

type BlenderDataCallback = (data: BlenderObjectData) => void;

export function syncWithBlender(callback: BlenderDataCallback) {
	let ws: WebSocket | null = null;
	let shouldReconnect = true;
	let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;

	const connect = () => {
		// Clear any existing reconnection timeout
		if (reconnectTimeout) {
			clearTimeout(reconnectTimeout);
			reconnectTimeout = null;
		}

		try {
			ws = new WebSocket("ws://localhost:8765");

			ws.onopen = () => {
				console.log("Connected to Blender");
			};

			ws.onmessage = (event) => {
				try {
					const data: BlenderObjectData = JSON.parse(event.data);
					callback(data);
				} catch (err) {
					console.error("Failed to parse message from Blender:", err);
				}
			};

			ws.onerror = (err) => {
				console.error("WS error", err);
			};

			ws.onclose = () => {
				console.log("Disconnected from Blender");
				
				// Only reconnect if we should (not manually closed)
				if (shouldReconnect) {
					console.log("Attempting to reconnect in 2 seconds...");
					reconnectTimeout = setTimeout(connect, 2000);
				}
			};
		} catch (err) {
			console.error("Failed to create WebSocket:", err);
			if (shouldReconnect) {
				console.log("Retrying connection in 2 seconds...");
				reconnectTimeout = setTimeout(connect, 2000);
			}
		}
	};

	// Start the initial connection
	connect();

	// Return a cleanup function to stop reconnection attempts
	return () => {
		shouldReconnect = false;
		if (reconnectTimeout) {
			clearTimeout(reconnectTimeout);
		}
		if (ws) {
			ws.close();
		}
	};
}

// Helper function for syncing with a Three.js camera
export function syncCameraWithBlender(camera: PerspectiveCamera) {
	return syncWithBlender((data) => {
		// Only update camera if the Blender object is a camera
		if (data.objectType === 'CAMERA' && data.fov !== null) {
			camera.position.set(data.position.x, data.position.y, data.position.z);
			camera.quaternion.set(
				data.quaternion.x,
				data.quaternion.y,
				data.quaternion.z,
				data.quaternion.w,
			);
			camera.fov = data.fov;
			camera.updateProjectionMatrix();
		}
	});
}

// Helper function for frame-based callbacks
export function syncFrameWithBlender(onFrame: (frame: number, fps: number) => void) {
	return syncWithBlender((data) => {
		onFrame(data.frame, data.fps);
	});
}