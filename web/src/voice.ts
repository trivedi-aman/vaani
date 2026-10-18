import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import type { CallHandle } from "./api";

export interface VoiceCall {
  hangUp: () => Promise<void>;
  setMuted: (muted: boolean) => void;
}

/**
 * Open a WebRTC voice connection for a call. Audio goes peer-to-peer to our
 * server; the call's bearer token authorises the offer and every ICE update.
 */
export async function startVoice(
  call: CallHandle,
  iceServers: RTCIceServer[],
  handlers: { onSpeaking: (who: "user" | "bot" | null) => void; onEnded: () => void; onError: (msg: string) => void },
): Promise<VoiceCall> {
  const audio = new Audio();
  audio.autoplay = true;
  const transport = new SmallWebRTCTransport({ iceServers });
  const client = new PipecatClient({
    transport,
    enableMic: true,
    enableCam: false,
    callbacks: {
      onTrackStarted: (track, participant) => {
        if (track.kind === "audio" && !participant?.local) {
          audio.srcObject = new MediaStream([track]);
          void audio.play().catch(() => handlers.onError("Tap anywhere to allow audio playback."));
        }
      },
      onUserStartedSpeaking: () => handlers.onSpeaking("user"),
      onUserStoppedSpeaking: () => handlers.onSpeaking(null),
      onBotStartedSpeaking: () => handlers.onSpeaking("bot"),
      onBotStoppedSpeaking: () => handlers.onSpeaking(null),
      onDisconnected: () => handlers.onEnded(),
      onError: (m) => handlers.onError(String((m as { data?: { message?: string } }).data?.message ?? "Voice error")),
    },
  });
  const headers = new Headers({ Authorization: `Bearer ${call.token}` });
  await client.connect({ webrtcRequestParams: { endpoint: `/api/calls/${call.call_id}/offer`, headers } });
  return {
    hangUp: async () => {
      await client.disconnect();
      audio.srcObject = null;
    },
    setMuted: (muted) => client.enableMic(!muted),
  };
}
