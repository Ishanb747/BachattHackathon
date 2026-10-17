// Voice client: ported from web/index.html (the working cascadevoice console).
// Keep the Safari fixes: one AudioContext at the device rate for capture AND
// playback, EC/NS/AGC off in Safari only, 100 ms playback slices, gain-ramp
// barge-in, and the WebSocket opened only after the audio graph is built.

// Mic capture: resample to 16 kHz and post 20 ms (320-sample) PCM-16 frames —
// exactly what the server's VAD expects.
const WORKLET = `
class PCMCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const o = (options && options.processorOptions) || {};
    this.ratio = (o.ctxRate || 16000) / 16000;
    this.frame = 320;
    this.buf = [];
  }
  process(inputs) {
    const raw = inputs[0] && inputs[0][0];
    if (!raw) return true;
    const n = Math.floor(raw.length / this.ratio);
    for (let i = 0; i < n; i++) {
      // Average each output sample's input window: a cheap low-pass, so 48 kHz
      // -> 16 kHz does not alias.
      const a = Math.floor(i * this.ratio);
      const b = Math.min(raw.length, Math.max(a + 1, Math.floor((i + 1) * this.ratio)));
      let sum = 0;
      for (let k = a; k < b; k++) sum += raw[k];
      this.buf.push(sum / (b - a));
    }
    while (this.buf.length >= this.frame) {
      const s = this.buf.splice(0, this.frame), pcm = new Int16Array(this.frame);
      for (let i = 0; i < this.frame; i++) {
        const c = Math.max(-1, Math.min(1, s[i]));
        pcm[i] = c < 0 ? c * 0x8000 : c * 0x7fff;
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor('pcm-capture', PCMCapture);
`;

export const isSafari = () => /^((?!chrome|chromium|android|edg).)*safari/i.test(navigator.userAgent);

/**
 * VoiceClient — one call. Handlers:
 *   onEvent(msg)    every JSON event from the server (plus {type:"_note"})
 *   onStatus(s)     idle | listening | transcribing | thinking | speaking
 *   onEnd(reason)   the call is over (socket closed / hangup)
 */
export class VoiceClient {
  constructor({ onEvent, onStatus, onEnd } = {}) {
    this.onEvent = onEvent || (() => {});
    this.onStatusCb = onStatus || (() => {});
    this.onEnd = onEnd || (() => {});
    this.ws = null; this.ctx = null; this.mic = null; this.worklet = null; this.gain = null;
    this.sources = []; this.playhead = 0; this.streamRate = null;
    this.active = false;
    this.status = "idle";
  }

  get playing() { return this.sources.length > 0; }
  setStatus(s) { this.status = s; this.onStatusCb(s); }

  async start(path = "/ws") {
    this.active = true;
    try {
      // One context for capture and playback at the device's own rate; the
      // capture worklet downsamples to the 16 kHz the server expects.
      // Safari's echo cancellation puts the mic in voice-processing mode, which
      // measured ~23 frames/s instead of 50 (half the audio lost); with it off,
      // 44-46. So Safari captures raw: use headphones there. Other browsers keep it.
      const safari = isSafari();
      this.mic = await navigator.mediaDevices.getUserMedia({ audio: {
        channelCount: 1, echoCancellation: !safari, noiseSuppression: !safari, autoGainControl: !safari } });
      if (!this.active) { this.teardown(); return; }
      this.ctx = new AudioContext();   // the device's own rate: Safari drops mic samples in a forced 16 kHz context
      await this.ctx.resume();
      this.gain = this.ctx.createGain(); this.gain.connect(this.ctx.destination);

      const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      await this.ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      if (!this.active) { this.teardown(); return; }
      this.worklet = new AudioWorkletNode(this.ctx, "pcm-capture", {
        processorOptions: { ctxRate: this.ctx.sampleRate }, numberOfOutputs: 0 });
      // Stream continuously, including while the agent speaks — the only window
      // in which the user can interrupt.
      this.worklet.port.onmessage = (e) => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(e.data);
      };
      this.ctx.createMediaStreamSource(this.mic).connect(this.worklet);

      // Open the socket only now: the server starts speaking the moment it
      // connects, and building the audio graph under playing audio makes Safari
      // glitch the greeting.
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}${path}`);
      ws.binaryType = "arraybuffer";
      ws.onmessage = (e) => {
        if (typeof e.data !== "string") { if (this.streamRate) this.playPcm(e.data, this.streamRate); return; }
        let msg;
        try { msg = JSON.parse(e.data); } catch (err) { console.warn(err); return; }
        this.handle(msg);
      };
      ws.onclose = () => { this.onEvent({ type: "_note", text: "Call disconnected" }); this.hangup("closed"); };
      this.ws = ws;
      this.setStatus("listening");
    } catch (err) {
      this.onEvent({ type: "error", message: `Could not start: ${err.message || err}` });
      this.hangup("error");
      throw err;
    }
  }

  handle(msg) {
    switch (msg.type) {
      case "status":
        // A status mid-sentence would flicker "listening" while audio still plays.
        if (!(msg.status === "listening" && this.playing)) this.setStatus(msg.status);
        break;
      case "audio_begin": this.streamRate = msg.sample_rate; break;
      case "audio_end": this.streamRate = null; break;
      case "control":
        if (msg.action === "stop_playback") this.stopPlayback(msg.fade_ms || 0);
        if (msg.action === "hangup") {
          const left = this.ctx ? Math.max(0, this.playhead - this.ctx.currentTime) : 0;
          setTimeout(() => this.hangup("agent"), left * 1000 + 1000);
        }
        break;
      default: break;
    }
    this.onEvent(msg);
  }

  // ── Playback: schedule each PCM chunk gaplessly after whatever is queued ──
  playPcm(arrayBuffer, rate) {
    const all = new Int16Array(arrayBuffer.slice(0, arrayBuffer.byteLength - (arrayBuffer.byteLength % 2)));
    // The cached greeting arrives as one multi-second chunk; one huge buffer
    // resampled in a go stutters in Safari. Play it as 100 ms slices.
    const slice = Math.round(rate * 0.1);
    for (let o = 0; o < all.length; o += slice) this.playSlice(all.subarray(o, o + slice), rate);
  }

  playSlice(pcm, rate) {
    if (!pcm.length || !this.ctx) return;
    const ctx = this.ctx;
    const buf = ctx.createBuffer(1, pcm.length, rate);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.gain);
    const at = Math.max(ctx.currentTime, this.playhead);
    src.start(at);
    this.playhead = at + buf.duration;
    this.sources.push(src);
    if (this.status !== "speaking") this.setStatus("speaking");
    src.onended = () => {
      this.sources = this.sources.filter((s) => s !== src);
      if (!this.sources.length && this.active) this.setStatus("listening");
    };
  }

  // Barge-in: ramp the gain down over fadeMs, then cut everything queued.
  stopPlayback(fadeMs = 0) {
    const cut = this.sources; this.sources = []; this.playhead = 0;
    const stopAll = () => cut.forEach((s) => { try { s.stop(); s.disconnect(); } catch {} });
    if (!this.ctx || !fadeMs || !cut.length) { stopAll(); return; }
    const ctx = this.ctx, gain = this.gain;
    const now = ctx.currentTime;
    gain.gain.cancelScheduledValues(now);
    gain.gain.setValueAtTime(gain.gain.value, now);
    gain.gain.linearRampToValueAtTime(0, now + fadeMs / 1000);
    setTimeout(() => {
      stopAll();
      if (!this.ctx) return;
      // Anything scheduled after the ramp (the next reply) plays at full level.
      gain.gain.cancelScheduledValues(this.ctx.currentTime);
      gain.gain.setValueAtTime(1, this.ctx.currentTime);
    }, fadeMs + 10);
  }

  sendText(text) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "user_text", text }));
      return true;
    }
    return false;
  }

  interrupt() {
    this.stopPlayback(90);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "interrupt" }));
  }

  teardown() {
    if (this.ws) { this.ws.onclose = null; try { this.ws.close(); } catch {} this.ws = null; }
    if (this.worklet) { this.worklet.disconnect(); this.worklet = null; }
    if (this.mic) { this.mic.getTracks().forEach((t) => t.stop()); this.mic = null; }
    this.stopPlayback(0);
    if (this.ctx) { try { this.ctx.close(); } catch {} }
    this.ctx = null;
  }

  hangup(reason = "user") {
    const was = this.active;
    this.active = false;
    this.teardown();
    this.setStatus("idle");
    if (was) this.onEnd(reason);
  }
}
