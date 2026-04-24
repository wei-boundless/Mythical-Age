"use client";

import { useEffect, useState } from "react";

export function ResizeHandle({
  onResize
}: {
  onResize: (delta: number) => void;
}) {
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!dragging) {
      return;
    }

    const onMouseMove = (event: MouseEvent) => {
      onResize(event.movementX);
    };
    const onMouseUp = () => {
      setDragging(false);
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);

    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [dragging, onResize]);

  return (
    <div
      aria-hidden
      className="group hidden w-4 cursor-col-resize items-center justify-center xl:flex"
      onMouseDown={() => setDragging(true)}
    >
      <div className="h-24 w-[2px] rounded-full bg-[var(--color-border-strong)] transition group-hover:h-32 group-hover:bg-[var(--color-soul)]" />
    </div>
  );
}
