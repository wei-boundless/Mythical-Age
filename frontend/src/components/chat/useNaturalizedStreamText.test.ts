import { describe, expect, it } from "vitest";

import { takeNaturalizedStreamSlice } from "./useNaturalizedStreamText";

describe("takeNaturalizedStreamSlice", () => {
  it("keeps short Chinese clauses together through punctuation", () => {
    const slice = takeNaturalizedStreamSlice("", "我已经读取了代码，继续检查。");

    expect(slice.text).toBe("我已经读取了代码，");
    expect(slice.delayMs).toBeGreaterThan(24);
  });

  it("streams long Chinese text in readable phrase chunks", () => {
    const slice = takeNaturalizedStreamSlice("", "我正在检查当前流式输出节奏");

    expect(slice.text).toBe("我正在检查");
    expect(slice.delayMs).toBe(24);
  });

  it("reveals code blocks by line instead of word by word", () => {
    const displayed = "```ts\n";
    const target = `${displayed}const value = makeNaturalText();\nconsole.log(value);\n`;
    const slice = takeNaturalizedStreamSlice(displayed, target);

    expect(slice.text).toBe("const value = makeNaturalText();\n");
    expect(slice.delayMs).toBeLessThanOrEqual(10);
  });

  it("keeps URLs and paths atomic", () => {
    const urlSlice = takeNaturalizedStreamSlice("", "https://example.com/docs/runtime-streaming 下一步");
    const pathSlice = takeNaturalizedStreamSlice("", "D:\\AI应用\\langchain-agent\\frontend\\src\\components 下一步");

    expect(urlSlice.text).toBe("https://example.com/docs/runtime-streaming");
    expect(pathSlice.text).toBe("D:\\AI应用\\langchain-agent\\frontend\\src\\components");
  });

  it("speeds up when the target text is far ahead of the displayed text", () => {
    const target = `${"a".repeat(500)}.`;
    const slice = takeNaturalizedStreamSlice("", target);

    expect(slice.text.length).toBeGreaterThan(1);
    expect(slice.delayMs).toBeLessThanOrEqual(8);
  });
});
