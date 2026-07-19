import { uploadBatches } from "./upload";

test("splits uploads into bounded batches without losing files", () => {
  const files = Array.from({ length: 5 }, (_, index) => new File([new ArrayBuffer(0)], `part-${index}`));
  expect(uploadBatches(files, 2, 1024).map(batch => batch.length)).toEqual([2, 2, 1]);
  expect(uploadBatches(files, 2, 1024).flat()).toEqual(files);
  expect(uploadBatches([], 2, 1024)).toEqual([]);
});

test("closes a batch when the next file would push it over the byte limit", () => {
  const sized = (size: number) => {
    const item = new File([new ArrayBuffer(0)], `f-${size}`);
    Object.defineProperty(item, "size", { value: size });
    return item;
  };
  const files = [sized(60), sized(60), sized(10)];
  expect(uploadBatches(files, 10, 100).map(batch => batch.map(item => item.size))).toEqual([[60], [60, 10]]);
});
