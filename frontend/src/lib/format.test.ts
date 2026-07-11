import { formatBytes, formatUptime } from "./format";

test("formats byte sizes for humans", () => {
  expect(formatBytes(512)).toBe("512 B");
  expect(formatBytes(2048)).toBe("2.0 KB");
  expect(formatBytes(17_179_869_184)).toBe("16.0 GB");
  expect(formatBytes(214_748_364_800)).toBe("200 GB");
});

test("formats uptime at sensible units", () => {
  expect(formatUptime(42)).toBe("42s");
  expect(formatUptime(95)).toBe("1m 35s");
  expect(formatUptime(7_305)).toBe("2h 1m");
});
