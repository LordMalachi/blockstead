/** Split an upload so no single request carries too many files or bytes. */
export function uploadBatches(files: File[], maxFiles = 200, maxBytes = 96 * 1024 * 1024): File[][] {
  const batches: File[][] = [];
  let batch: File[] = [];
  let bytes = 0;
  for (const file of files) {
    if (batch.length && (batch.length >= maxFiles || bytes + file.size > maxBytes)) {
      batches.push(batch); batch = []; bytes = 0;
    }
    batch.push(file); bytes += file.size;
  }
  if (batch.length) batches.push(batch);
  return batches;
}
