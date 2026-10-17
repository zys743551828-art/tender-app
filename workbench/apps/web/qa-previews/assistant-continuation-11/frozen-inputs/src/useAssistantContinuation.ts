import { useCallback, useEffect, useRef } from "react";

/** Follow the input only while continuing; reading history is always a user choice. */
export function useAssistantContinuation(ready: boolean, autoPosition = true) {
  const content = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const initialized = useRef(false);
  const interacted = useRef(false);
  const following = useRef(false);
  const continueWriting = useCallback(() => {
    initialized.current = true;
    interacted.current = true;
    following.current = true;
    input.current?.focus({ preventScroll: true });
    input.current?.scrollIntoView?.({ block: "center", behavior: "instant" });
  }, []);
  useEffect(() => {
    if (!ready || initialized.current || !autoPosition) return;
    if (interacted.current) return;
    const frame = requestAnimationFrame(() => {
      if (!interacted.current) continueWriting();
    });
    return () => cancelAnimationFrame(frame);
  }, [ready, autoPosition, continueWriting]);
  useEffect(() => {
    let frame = 0;
    function stopFollowing() {
      interacted.current = true;
      following.current = false;
    }
    function pointer(event: PointerEvent) {
      interacted.current = true;
      following.current = event.target === input.current;
    }
    function keydown(event: KeyboardEvent) {
      if (
        event.key === "Tab" ||
        (event.target !== input.current &&
          [
            "PageUp",
            "PageDown",
            "Home",
            "End",
            "ArrowUp",
            "ArrowDown",
            " ",
          ].includes(event.key))
      )
        stopFollowing();
    }
    function focus(event: FocusEvent) {
      if (event.target !== input.current) stopFollowing();
    }
    function maintainVisibleInput() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const element = input.current;
        if (
          !following.current ||
          !element ||
          document.activeElement !== element
        )
          return;
        const box = element.getBoundingClientRect();
        const viewport = window.visualViewport;
        const top = (viewport?.offsetTop ?? 0) + 72;
        const bottom =
          (viewport?.offsetTop ?? 0) +
          (viewport?.height ?? window.innerHeight) -
          16;
        if (box.top < top || box.bottom > bottom)
          element.scrollIntoView?.({ block: "center", behavior: "instant" });
      });
    }
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(maintainVisibleInput);
    if (content.current) observer?.observe(content.current);
    window.addEventListener("wheel", stopFollowing, {
      passive: true,
      capture: true,
    });
    window.addEventListener("touchmove", stopFollowing, {
      passive: true,
      capture: true,
    });
    window.addEventListener("pointerdown", pointer, true);
    window.addEventListener("keydown", keydown, true);
    window.addEventListener("focusin", focus, true);
    window.addEventListener("resize", maintainVisibleInput);
    window.visualViewport?.addEventListener("resize", maintainVisibleInput);
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("wheel", stopFollowing, true);
      window.removeEventListener("touchmove", stopFollowing, true);
      window.removeEventListener("pointerdown", pointer, true);
      window.removeEventListener("keydown", keydown, true);
      window.removeEventListener("focusin", focus, true);
      window.removeEventListener("resize", maintainVisibleInput);
      window.visualViewport?.removeEventListener(
        "resize",
        maintainVisibleInput,
      );
    };
  }, []);
  return { content, input, continueWriting };
}
