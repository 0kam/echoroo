import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

export function makeWav(seconds: number, sampleRate = 16000): Buffer {
  const frameCount = Math.floor(seconds * sampleRate);
  const dataSize = frameCount * 2;
  const buffer = Buffer.alloc(44 + dataSize);

  buffer.write('RIFF', 0, 'ascii');
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write('WAVE', 8, 'ascii');
  buffer.write('fmt ', 12, 'ascii');
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36, 'ascii');
  buffer.writeUInt32LE(dataSize, 40);

  for (let frame = 0; frame < frameCount; frame += 1) {
    const sample = Math.round(Math.sin((2 * Math.PI * 440 * frame) / sampleRate) * 0.5 * 32767);
    buffer.writeInt16LE(sample, 44 + frame * 2);
  }

  return buffer;
}

export function wavPath(name: string, seconds: number): string {
  const directory = resolve(process.cwd(), 'test-results', 'upload-fixtures');
  mkdirSync(directory, { recursive: true });
  const filePath = resolve(directory, name);
  writeFileSync(filePath, makeWav(seconds));
  return filePath;
}
