/**
 * TORCH Web GUI — Minimal MIDI Player (vanilla JS, Web Audio API).
 *
 * Plays Standard MIDI Format 0 and 1 files using simple oscillators
 * (square/triangle waves) for a chiptune-style preview. Not game-accurate
 * — uses synthesised tones instead of GBA voicegroup samples — but enough
 * to identify each track by melody and tempo.
 *
 * API:
 *   midiPlayer.canPlay()            — true if Web Audio is available
 *   midiPlayer.play(url)            — fetch + play a .mid file
 *   midiPlayer.stop()               — stop playback
 *   midiPlayer.isPlaying()          — true if currently playing
 *   midiPlayer.onStop = fn          — callback when playback ends
 */

const midiPlayer = (() => {
  let ctx = null;         // AudioContext (lazy-init)
  let playing = false;
  let stopRequested = false;
  let timeouts = [];      // scheduled setTimeout IDs
  let activeOscs = [];    // {osc, gain} pairs for cleanup
  let onStopCallback = null;

  function canPlay() {
    return !!(window.AudioContext || window.webkitAudioContext);
  }

  function getCtx() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      ctx = new AC();
    }
    return ctx;
  }

  // -----------------------------------------------------------------------
  // MIDI binary parser
  // -----------------------------------------------------------------------

  function parseMidi(buf) {
    const view = new DataView(buf);
    let pos = 0;

    function read(n) {
      const slice = new Uint8Array(buf, pos, n);
      pos += n;
      return slice;
    }
    function readU16() { const v = view.getUint16(pos); pos += 2; return v; }
    function readU32() { const v = view.getUint32(pos); pos += 4; return v; }
    function readVarLen() {
      let val = 0;
      for (let i = 0; i < 4; i++) {
        const b = view.getUint8(pos++);
        val = (val << 7) | (b & 0x7F);
        if (!(b & 0x80)) break;
      }
      return val;
    }

    // Header chunk
    const headerTag = String.fromCharCode(...read(4));
    if (headerTag !== "MThd") return null;
    readU32(); // header length (always 6)
    const format = readU16();
    const numTracks = readU16();
    const ticksPerBeat = readU16();

    // Parse tracks
    const tracks = [];
    for (let t = 0; t < numTracks; t++) {
      const trackTag = String.fromCharCode(...read(4));
      if (trackTag !== "MTrk") break;
      const trackLen = readU32();
      const trackEnd = pos + trackLen;
      const events = [];
      let runningStatus = 0;

      while (pos < trackEnd) {
        const delta = readVarLen();
        let statusByte = view.getUint8(pos);

        if (statusByte & 0x80) {
          pos++;
          runningStatus = statusByte;
        } else {
          statusByte = runningStatus;
        }

        const type = statusByte & 0xF0;
        const ch = statusByte & 0x0F;

        if (type === 0x90) {
          // Note on
          const note = view.getUint8(pos++);
          const vel = view.getUint8(pos++);
          events.push({ delta, type: vel > 0 ? "noteOn" : "noteOff", ch, note, vel });
        } else if (type === 0x80) {
          // Note off
          const note = view.getUint8(pos++);
          const vel = view.getUint8(pos++);
          events.push({ delta, type: "noteOff", ch, note, vel });
        } else if (type === 0xA0 || type === 0xB0 || type === 0xE0) {
          pos += 2; // skip 2-byte messages
          events.push({ delta, type: "skip" });
        } else if (type === 0xC0 || type === 0xD0) {
          pos += 1; // skip 1-byte messages
          events.push({ delta, type: "skip" });
        } else if (statusByte === 0xFF) {
          // Meta event
          const metaType = view.getUint8(pos++);
          const metaLen = readVarLen();
          if (metaType === 0x51 && metaLen === 3) {
            // Tempo change
            const b0 = view.getUint8(pos);
            const b1 = view.getUint8(pos + 1);
            const b2 = view.getUint8(pos + 2);
            const tempo = (b0 << 16) | (b1 << 8) | b2;
            events.push({ delta, type: "tempo", tempo });
          } else {
            events.push({ delta, type: "skip" });
          }
          pos += metaLen;
        } else if (statusByte === 0xF0 || statusByte === 0xF7) {
          // SysEx
          const sysLen = readVarLen();
          pos += sysLen;
          events.push({ delta, type: "skip" });
        } else {
          // Unknown — skip a byte to avoid infinite loop
          pos++;
          events.push({ delta, type: "skip" });
        }
      }
      pos = trackEnd; // ensure we're at track end
      tracks.push(events);
    }

    return { format, numTracks, ticksPerBeat, tracks };
  }

  // -----------------------------------------------------------------------
  // Convert parsed MIDI to timed note events
  // -----------------------------------------------------------------------

  function midiToTimedEvents(midi) {
    // Merge all tracks into a single timeline
    const merged = [];

    for (const track of midi.tracks) {
      let tickPos = 0;
      for (const ev of track) {
        tickPos += ev.delta;
        merged.push({ ...ev, tick: tickPos });
      }
    }

    // Sort by tick position
    merged.sort((a, b) => a.tick - b.tick);

    // Convert ticks to seconds
    let tempo = 500000; // default: 120 BPM
    let lastTick = 0;
    let lastTime = 0;
    const timed = [];

    for (const ev of merged) {
      const deltaTick = ev.tick - lastTick;
      const deltaTime = (deltaTick / midi.ticksPerBeat) * (tempo / 1000000);
      lastTime += deltaTime;
      lastTick = ev.tick;

      if (ev.type === "tempo") {
        tempo = ev.tempo;
      } else if (ev.type === "noteOn" || ev.type === "noteOff") {
        timed.push({ time: lastTime, type: ev.type, ch: ev.ch, note: ev.note, vel: ev.vel });
      }
    }

    return timed;
  }

  // -----------------------------------------------------------------------
  // Oscillator playback
  // -----------------------------------------------------------------------

  function noteToFreq(note) {
    return 440 * Math.pow(2, (note - 69) / 12);
  }

  // Channel -> waveform mapping for variety
  const CHANNEL_WAVES = [
    "square", "square", "sawtooth", "triangle",
    "square", "triangle", "sawtooth", "square",
    "triangle", "square",  // ch 9 (drums) handled separately
    "square", "triangle", "sawtooth", "square", "triangle", "square",
  ];

  function playEvents(events) {
    const audio = getCtx();
    const masterGain = audio.createGain();
    masterGain.gain.value = 0.15; // keep it quiet — chiptune can be harsh
    masterGain.connect(audio.destination);

    const activeNotes = {}; // "ch-note" -> {osc, gain}

    stopRequested = false;
    playing = true;

    for (const ev of events) {
      if (ev.ch === 9) continue; // skip percussion channel

      const id = ev.type === "noteOn"
        ? setTimeout(() => {
            if (stopRequested) return;
            const key = `${ev.ch}-${ev.note}`;

            // Stop existing note on same key
            if (activeNotes[key]) {
              try { activeNotes[key].osc.stop(); } catch (_) {}
              delete activeNotes[key];
            }

            const osc = audio.createOscillator();
            const gain = audio.createGain();
            osc.type = CHANNEL_WAVES[ev.ch] || "square";
            osc.frequency.value = noteToFreq(ev.note);
            gain.gain.value = (ev.vel / 127) * 0.3;
            osc.connect(gain);
            gain.connect(masterGain);
            osc.start();
            activeNotes[key] = { osc, gain };
            activeOscs.push({ osc, gain });
          }, ev.time * 1000)
        : setTimeout(() => {
            if (stopRequested) return;
            const key = `${ev.ch}-${ev.note}`;
            if (activeNotes[key]) {
              const { osc, gain } = activeNotes[key];
              // Quick fade out to avoid clicks
              gain.gain.linearRampToValueAtTime(0, audio.currentTime + 0.02);
              setTimeout(() => { try { osc.stop(); } catch (_) {} }, 30);
              delete activeNotes[key];
            }
          }, ev.time * 1000);

      timeouts.push(id);
    }

    // Schedule end-of-playback
    const lastTime = events.length > 0 ? events[events.length - 1].time : 0;
    timeouts.push(setTimeout(() => {
      cleanup();
    }, (lastTime + 1) * 1000));
  }

  function cleanup() {
    playing = false;
    stopRequested = true;
    for (const id of timeouts) clearTimeout(id);
    timeouts = [];
    for (const { osc, gain } of activeOscs) {
      try { gain.gain.value = 0; osc.stop(); } catch (_) {}
    }
    activeOscs = [];
    if (onStopCallback) onStopCallback();
  }

  async function play(url) {
    stop();
    try {
      const resp = await fetch(url);
      if (!resp.ok) return;
      const buf = await resp.arrayBuffer();
      const midi = parseMidi(buf);
      if (!midi) return;
      const events = midiToTimedEvents(midi);
      if (events.length === 0) return;
      playEvents(events);
    } catch (_) {
      cleanup();
    }
  }

  function stop() {
    cleanup();
  }

  function isPlaying() {
    return playing;
  }

  return {
    canPlay,
    play,
    stop,
    isPlaying,
    set onStop(fn) { onStopCallback = fn; },
  };
})();

export { midiPlayer };
