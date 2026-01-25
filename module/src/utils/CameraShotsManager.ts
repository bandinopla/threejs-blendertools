import {
	AnimationAction,
	AnimationMixer,
	LoopOnce,
	type AnimationClip,
	type PerspectiveCamera,
} from "three";

export class ShotsManager {
	private shots: AnimatedCamera[];
	private sequence?: AnimatedCamera[];
	private currentShotIndex: number = -1;
	private isPlaying: boolean = false;

	/**
	 * If set, when playing, this camera will be positioned, rotated and FOV adjusted to match the shots.
	 */
	targetCamera?: PerspectiveCamera;

	private frameScripts: { time:number, callback:VoidFunction, called?:boolean }[] = [];
	private playheadTime = 0;
	private onShotsCompleted?:VoidFunction;

	/**
	 * Set to ture when testing / designing the shots... it will restart once the sequence is done playing.
	 */
	public loop = false;

	/**
	 * This class will manage the sequencing of animation clips	
	 * @param cameras Array of cameras. Their names MUST coincide with the animation's clip name.
	 * @param clips Array of animation clips. Their names MUST coincide with the camera's name.
	 */
	constructor(
		readonly cameras: PerspectiveCamera[],
		readonly clips: AnimationClip[],
	) {
		this.shots = [];
		for (let i = 0; i < cameras.length; i++) {
			this.shots.push(
				new AnimatedCamera(
					cameras[i],
					clips.find((c) => c.name == cameras[i].name)!,
				),
			);
		}
	}

	/**
	 * Defines the sequence of shots to be played
	 * @param shotsNames Array of shot names
	 */
	config(shotsNames: string[]) {
		this.sequence = [];
 
		for (let i = 0; i < shotsNames.length; i++) {
			const shot = this.shots.find((s) => s.clip.name === shotsNames[i]);
			if (shot) {
				this.sequence.push(shot); 
			}
		} 
	}

	/**
	 * Adds a frame script to be executed at a specific frame
	 * @param frame Frame number
	 * @param callback Callback function
	 * @param baseFPS Base FPS (default is 24 in Blender)
	 */
	addFrameScript( frame:number, callback:VoidFunction, baseFPS = 24 )
	{
		this.frameScripts.push({ time: frame/baseFPS, callback });
	}

	/**
	 * Set the duration of a shot by name, adjusting its timeScale
	 */
	setShotDuration(shotName: string, newDuration: number): boolean {
		const shot = this.shots.find(s => s.clip.name === shotName);
		
		if (!shot) {
			console.warn(`Shot "${shotName}" not found`);
			return false;
		}

		shot.setDuration(newDuration);
		return true;
	}

	/**
	 * starts playing the sequence of shots one by one.
	 * Must call `.update` on every frame for this to work.
	 */
	play( onCompleted?:VoidFunction ) {
		if (!this.sequence || this.sequence.length === 0) {
			console.warn("No sequence configured");
			return;
		}
		this.playheadTime = 0;
		this.onShotsCompleted = onCompleted;

		for (const script of this.frameScripts) {
			script.called = false;
		}

		this.isPlaying = true;
		this.currentShotIndex = 0;
		this.playCurrentShot();
	}

	/**
	 * Manually set the time in the sequence. 
	 * @param time Time in seconds
	 * @param camera the camera to be moved to the shot's angle.
	 * @returns 
	 */
	scrub(time: number, camera: PerspectiveCamera) {
		if (!this.sequence || this.sequence.length === 0) return;

		this.isPlaying = false;

		let accumulatedTime = 0;
		let targetShot: AnimatedCamera | null = null;
		let scrubTime = 0;

		// Stop all shots first
		for (const seq of this.sequence) {
			seq.stop();
		}

		// Find which shot should be active at this time
		for (let i = 0; i < this.sequence.length; i++) {
			const seq = this.sequence[i];
			const clipDuration = seq.getEffectiveDuration();
			const shotStart = accumulatedTime;
			const shotEnd = accumulatedTime + clipDuration;
			
			if (time >= shotStart && time < shotEnd) {
				targetShot = seq;
				scrubTime = time - shotStart;
				break;
			}

			accumulatedTime += clipDuration;
		}

		// Handle case where time is at or beyond the end
		if (!targetShot && this.sequence.length > 0) {
			const lastShot = this.sequence[this.sequence.length - 1];
			targetShot = lastShot;
			scrubTime = lastShot.getEffectiveDuration(); // Clamp to end
		}

		// Apply the scrubbed time
		if (targetShot) {
			targetShot.scrubTo(scrubTime);

			this.syncCamera(camera, targetShot.camera)
		}

		
	}

	private playCurrentShot() {
		if (!this.sequence || this.currentShotIndex >= this.sequence.length) {
			return;
		}

		const currentShot = this.sequence[this.currentShotIndex];

		// Set up the shot to play once and stop at the end
		currentShot.play(() => {
			// This callback is triggered when the animation finishes
			this.onShotFinished();
		});
	}

	private onShotFinished() {
		this.currentShotIndex++;

		if (this.currentShotIndex >= this.sequence!.length) {
 
			if( this.loop )
			{
				this.currentShotIndex = 0;
			}
			else
			{
				this.isPlaying = false;
				if( this.onShotsCompleted )
				{
					this.onShotsCompleted();
				}

				return;
			}
		}

		this.playCurrentShot();

		// if (this.currentShotIndex < this.sequence!.length) {
		// 	// Play the next shot
		// 	this.playCurrentShot();
		// } else {
		// 	// Sequence finished
		// 	this.isPlaying = false;
		// 	console.log("Sequence finished");
		// }
	}

	private syncCamera(camera: PerspectiveCamera, target: PerspectiveCamera) {
		camera.position.copy(target.position);
		camera.quaternion.copy(target.quaternion);
		camera.fov = target.fov;
		camera.updateProjectionMatrix();
	}

	/**
	 * This should be called when playing the sequence. 
	 * @param delta the time passed since the last frame render
	 * @returns 
	 */
	update(delta: number) {
		if (!this.isPlaying || !this.sequence || this.currentShotIndex < 0) {
			return;
		}

		if (this.targetCamera) {

			this.syncCamera(this.targetCamera, this.sequence[this.currentShotIndex].camera)
			
		}

		this.playheadTime += delta;

		// Update only the current shot
		if (this.currentShotIndex < this.sequence.length) {
			this.sequence[this.currentShotIndex].update(delta);
		}

		// check frame script
		for (const script of this.frameScripts) {
			if (script.time < this.playheadTime && !script.called) {
				script.called = true;
				script.callback(); 
			}
		}
	}
}

class AnimatedCamera {
	readonly mixer: AnimationMixer;
	readonly action: AnimationAction;
	private onFinishCallback?: () => void;

	constructor(
		readonly camera: PerspectiveCamera,
		readonly clip: AnimationClip,
	) {
		this.mixer = new AnimationMixer(camera);
		this.action = this.mixer.clipAction(clip);

		this.action.setLoop(LoopOnce, 1);
		this.action.clampWhenFinished = true;

		this.mixer.addEventListener("finished", () => {
			if (this.onFinishCallback) {
				this.onFinishCallback();
			}
		});
	}

	/**
	 * Set the duration of this animation by adjusting timeScale
	 */
	setDuration(newDuration: number) {
		const originalDuration = this.clip.duration;
		// timeScale = original / desired
		// If original is 3s and we want 6s, timeScale = 0.5 (play slower)
		// If original is 3s and we want 1.5s, timeScale = 2 (play faster)
		this.action.timeScale = originalDuration / newDuration;
		
		console.log(`Shot "${this.clip.name}" timeScale set to ${this.action.timeScale.toFixed(3)} (${originalDuration.toFixed(2)}s → ${newDuration.toFixed(2)}s)`);
	}

	/**
	 * Get the effective duration accounting for timeScale
	 */
	getEffectiveDuration(): number {
		return this.clip.duration / this.action.timeScale;
	}

	play(onFinish: () => void) {
		this.onFinishCallback = onFinish;
		this.action.reset();
		this.action.play();
	}

	stop() {
		this.action.stop();
	}

	scrubTo(time: number) {
		this.action.reset();
		this.action.play();
		this.action.paused = true;
		
		// Convert effective time to actual animation time accounting for timeScale
		// If timeScale is 2 (plays 2x faster), and we want to scrub to effective time 1s,
		// the actual animation time should be 2s worth of animation
		const actualAnimationTime = time * this.action.timeScale;
		
		// Clamp to valid range
		this.action.time = Math.max(0, Math.min(actualAnimationTime, this.clip.duration));
		
		this.mixer.update(0);
	}

	update(delta: number) {
		this.mixer.update(delta);
	}
}
