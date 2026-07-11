"use client";

import { useEffect, useRef, useState } from "react";
import { WS_URL } from "@/lib/api";
import type { WsMessage } from "@/lib/types";

export type LinkStatus = "connecting" | "linked" | "lost";

/** Auto-reconnecting WebSocket to the backend event stream. */
export function useWebSocket(onMessage: (msg: WsMessage) => void): LinkStatus {
  const [status, setStatus] = useState<LinkStatus>("connecting");
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout>;
    let ping: ReturnType<typeof setInterval>;
    let closed = false;

    const connect = () => {
      setStatus("connecting");
      ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        setStatus("linked");
        ping = setInterval(() => ws?.send("ping"), 25000);
      };
      ws.onmessage = (e) => {
        try {
          handlerRef.current(JSON.parse(e.data) as WsMessage);
        } catch {
          /* malformed frame — ignore */
        }
      };
      ws.onclose = () => {
        clearInterval(ping);
        if (!closed) {
          setStatus("lost");
          retry = setTimeout(connect, 2500);
        }
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      clearInterval(ping);
      ws?.close();
    };
  }, []);

  return status;
}
