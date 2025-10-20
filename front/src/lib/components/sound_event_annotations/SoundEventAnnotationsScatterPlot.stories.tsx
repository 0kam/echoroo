import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import SoundEventAnnotationsScatterPlot from "@/lib/components/sound_event_annotations/SoundEventAnnotationsScatterPlot";

import type { ScatterPlotData, Tag } from "@/lib/types";

const meta: Meta<typeof SoundEventAnnotationsScatterPlot> = {
  title: "SoundEventAnnotations/ScatterPlot",
  component: SoundEventAnnotationsScatterPlot,
  args: {
    onClickSoundEvent: fn(),
  },
};

export default meta;

type Story = StoryObj<typeof SoundEventAnnotationsScatterPlot>;

const makeTag = (key: string, value: string): Tag => ({
  key,
  value,
  canonical_name: value,
});

const speciesTags: Tag[] = [
  makeTag("Species", "Cat"),
  makeTag("Species", "Dog"),
  makeTag("Species", "Bird"),
  makeTag("Species", "Human"),
  makeTag("Species", "Elephant"),
  makeTag("Species", "Lion"),
];

const behaviourTags: Tag[] = [
  makeTag("Behaviour", "Barking"),
  makeTag("Behaviour", "Meowing"),
  makeTag("Behaviour", "Roaring"),
  makeTag("Behaviour", "Singing"),
  makeTag("Behaviour", "Trumpeting"),
  makeTag("Behaviour", "Howling"),
];

const qualityTags: Tag[] = [
  makeTag("Quality", "Good"),
  makeTag("Quality", "Bad"),
  makeTag("Quality", "Meh"),
];

const locationTags: Tag[] = [
  makeTag("Location", "Forest"),
  makeTag("Location", "City"),
  makeTag("Location", "Beach"),
  makeTag("Location", "Desert"),
  makeTag("Location", "Mountain"),
];

const timeOfDateTags: Tag[] = [
  makeTag("Time of Day", "Morning"),
  makeTag("Time of Day", "Afternoon"),
  makeTag("Time of Day", "Evening"),
  makeTag("Time of Day", "Night"),
];

function randomFeatures() {
  return [
    { name: "low_freq", value: Math.random() },
    { name: "high_freq", value: Math.random() },
    { name: "duration", value: Math.random() },
    { name: "snr", value: Math.random() },
  ];
}

function randomSoundEventTags() {
  const tags = [];

  if (Math.random() < 0.5) {
    tags.push(speciesTags[Math.floor(Math.random() * speciesTags.length)]);
  }

  if (Math.random() < 0.5) {
    tags.push(behaviourTags[Math.floor(Math.random() * behaviourTags.length)]);
  }

  if (Math.random() < 0.5) {
    tags.push(qualityTags[Math.floor(Math.random() * qualityTags.length)]);
  }
  return tags;
}

function randomRecordingTags() {
  const tags = [];

  if (Math.random() < 0.5) {
    tags.push(locationTags[Math.floor(Math.random() * locationTags.length)]);
  }

  if (Math.random() < 0.5) {
    tags.push(
      timeOfDateTags[Math.floor(Math.random() * timeOfDateTags.length)],
    );
  }

  return tags;
}

const data: ScatterPlotData[] = Array.from({ length: 100 }, (_, index) => ({
  uuid: index.toString(),
  features: randomFeatures(),
  tags: randomSoundEventTags(),
  recording_tags: randomRecordingTags(),
}));

export const Empty: Story = {
  args: { data: [] },
};

export const SinglePoint: Story = {
  args: { data: data.slice(0, 1) },
};

export const ManyPoints: Story = {
  args: { data: data },
};
