---
name: accessibility-media
description: Use when checking video and audio accessibility including transcripts, captions, audio descriptions, and media player controls.
---

# Make Media Accessible

Ensure audio and video content is accessible through text alternatives, synchronized captions, and audio descriptions.

## Quick Reference

| Media Type | Requirement | Implementation |
|------------|-------------|----------------|
| **Audio-only** | Transcript text | Link near player with full content |
| **Video-only** | Alternative text or audio | Descriptive audio track |
| **Prerecorded video** | Captions | WebVTT track synchronized with dialogue |
| **Prerecorded video** | Audio description | Narrated visual details or text alternative |
| **Live audio** | Real-time captions | CART or ASR with human review |
| **Auto-playing audio** | Volume/pause control | Stop mechanism within 3 seconds |

## Critical Checks

### Audio-Only Content

For recordings with sound only (podcasts, interviews, speeches):

- [ ] Text transcript provided
- [ ] Transcript accessible near audio player
- [ ] All spoken content included verbatim
- [ ] Sound effects and music described [optional]
- [ ] Speaker identification when multiple speakers

```html
<audio controls>
  <source src="interview.mp3" type="audio/mpeg">
</audio>
<a href="interview-transcript.html">Read transcript</a>
```

### Video-Only Content

For recordings with visuals only (demonstrations, animations without sound):

- [ ] Descriptive audio track OR text alternative
- [ ] Visual actions and events described
- [ ] Text summary accessible near video

### Prerecorded Synchronized Media

For video with audio (movies, tutorials, presentations):

**Captions (Required Level A):**
- [ ] Synchronized with audio timing
- [ ] User can enable/disable captions
- [ ] All dialogue included
- [ ] Speaker identification when unclear visually
- [ ] Sound effects and music described when relevant

**Formats:**
- WebVTT (.vtt) - Recommended
- SRT (.srt)
- TTML (.ttml)

```html
<video controls>
  <source src="video.mp4" type="video/mp4">
  <track kind="captions" src="captions.vtt" srclang="en" label="English">
</video>
```

**Audio Description (Required Level AA):**
- [ ] Describes important visual content
- [ ] Fits within natural audio pauses
- [ ] Or: Full text alternative provided with visual descriptions

**Options:**
1. Second audio track with descriptions mixed in
2. Extended descriptions that pause video
3. Detailed text transcript describing visuals

```html
<!-- Audio description track -->
<video controls>
  <source src="video.mp4" type="video/mp4">
  <track kind="descriptions" src="audio-desc.vtt" srclang="en" label="Audio Description">
  <track kind="captions" src="captions.vtt" srclang="en" label="English">
</video>
```

### Live Content

For streaming and real-time broadcasts:

**Live Captions (Required Level AA):**
- [ ] Real-time captioning for live audio content
- [ ] Professional CART (Communication Access Realtime Translation) service
- [ ] Or: Accurate ASR (Automatic Speech Recognition) with human correction
- [ ] Maximum 3-second delay

### Audio Control

For auto-playing audio (Level A):

- [ ] Mechanism to pause or stop audio
- [ ] Or: Mechanism to control volume independently from system
- [ ] Must be available within first 3 seconds

```html
<!-- Audio with accessible controls -->
<audio controls>
  <source src="podcast.mp3" type="audio/mpeg">
</audio>

<!-- Or custom controls -->
<div role="region" aria-label="Audio player">
  <button aria-label="Play">▶</button>
  <button aria-label="Pause">⏸</button>
  <input type="range" aria-label="Volume" min="0" max="100">
</div>
```

### Media Player Controls

Ensure player interface is accessible:

- [ ] All controls keyboard accessible (Tab, Enter, Space)
- [ ] Buttons have accessible names (Play, Pause, Mute, Volume)
- [ ] Focus visible on all controls
- [ ] Captions can be toggled on/off
- [ ] Volume adjustable independent of system
- [ ] Time slider draggable and keyboard accessible
- [ ] Full-screen toggle available

**Accessible Player Options:**
- Able Player - Accessibly Plus
- Video.js with accessibility plugins
- YouTube (caption capabilities)
- Vimeo (caption and audio description support)

## RGAA Correspondences

- **4.1-4.8**: Multimedia content requirements
- **4.9**: Alternative for prerecorded audio-only
- **4.10**: Alternative for prerecorded video-only
- **4.11**: Captions for prerecorded synchronized media
- **4.12**: Audio description or full text alternative
- **4.13**: Live captions for synchronized media

## Related Skills

- Use `accessibility-keyboard` for player keyboard navigation
- Use `accessibility-color-contrast` for caption text contrast
- Use `accessibility-focus` for player control focus management
- Use `accessibility-aria` for custom player controls
- Use `accessibility-evaluation` for comprehensive media testing methodology

## Testing

For comprehensive media testing procedures, use `accessibility-evaluation`.

## Resources

- [Understanding Audio-only and Video-only (Prerecorded)](https://www.w3.org/WAI/WCAG22/Understanding/audio-only-and-video-only-prerecorded)
- [Understanding Captions (Prerecorded)](https://www.w3.org/WAI/WCAG22/Understanding/captions-prerecorded)
- [Understanding Audio Description](https://www.w3.org/WAI/WCAG22/Understanding/audio-description-prerecorded)
- [Accessible Media Players](https://www.w3.org/WAI/media/av/players/)
- [WebVTT Specification](https://www.w3.org/TR/webvtt/)
