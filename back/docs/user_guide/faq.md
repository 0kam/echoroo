# FAQ

## Starting Up Whombat

### I'm having trouble logging in. What should I do?

If you're logging into Whombat for the first time, you might not have a personalized username and password yet.
Don't worry, Whombat automatically sets up a default user during initialization.

To get started:

- Username: **admin**
- Password: **admin**

After your initial login, head over to your user profile to customize both your username and password to something more personalized and secure.

## Annotation & Tagging

### How do I use standardized species names?

Whombat integrates with GBIF (Global Biodiversity Information Facility) to help you use standardized, taxonomically correct species names when tagging:

1. **Start typing a species name**: When adding a tag, begin typing the scientific or common name
2. **Select from GBIF suggestions**: Whombat will search GBIF's taxonomy and show matching species
3. **Choose the correct species**: Select the appropriate species from the dropdown to ensure standardized naming

This ensures your annotations use consistent, globally recognized species identifiers that can be easily shared and compared with other datasets.

!!! tip "Scientific vs. Common Names"

    While you can search using common names, GBIF results prioritize scientific names for accuracy. We recommend using scientific names when possible for better data interoperability.

### Can I restrict tag searches to species only?

Yes! When the "GBIF Only" option is enabled in tag search, only species-level taxonomic results from GBIF will be shown. This helps maintain consistency and prevents the use of non-standard or genus-level tags when species-level identification is required.

## Focusing on sounds

### Can I isolate sounds within specific frequency range?

If you know your target sounds fall within a specific frequency range, you can apply a bandpass filter to focus your attention and filter out extraneous noise.

To do this:

1. **Access Spectrogram Settings**: Locate the Spectrogram Settings within the annotation interface.
      (You may need to refer to the [Spectrogram Settings](guides/spectrogram_display.md#spectrogram-settings) section of the documentation for the precise location).
2. **Apply Bandpass Filter**: Adjust the filter settings to define your desired frequency range.

!!! tip "Additional tips"

    **Experiment with Filter Settings**: Try different frequency ranges to find the optimal settings for isolating your target sounds.
    **Combine with Denoising**: Use the denoising feature in conjunction with filtering to further enhance clarity.

## Ultrasonic recordings

### I have time expanded recordings, can I use them?

Whombat fully supports time-expanded audio recordings, commonly used in bioacoustics research to analyze high-frequency vocalizations like bat calls.
While Whombat assumes recordings are not time-expanded by default, you can easily adjust for this:

1. **Navigate to the Recording Detail Page**: Access the page dedicated to the specific recording you want to work with.
2. **Update Time Expansion Factor**: In the recording media info, you'll find an option to specify the "Time Expansion Factor" used during recording.
      Enter the correct value here.

!!! warning "Adjust the time expansion early"

    Set the time expansion factor as soon as you upload a time-expanded recording to ensure accurate frequency calculations from the start.

??? tip "Restoring the original samplerate"

    While it's possible to unexpand recordings (refer to the [bats section](https://xeno-canto.org/help/FAQ#bats) of the xeno-canto documentation for tips), Whombat allows you to work directly with time-expanded recordings without altering the original data. We recommend this approach as it maintains the integrity of your source material and provides a clear record of how the recording was created.

## Access Control & Collaboration

### What are visibility settings?

Whombat allows you to control who can view and edit your datasets and annotation projects through visibility settings. There are three levels:

- **Private**: Only you can access the resource
- **Group**: Members of specific groups you select can access the resource
- **Public**: All users in the system can access the resource

You can set visibility when creating a new dataset or annotation project, or update it later in the settings.

### How do I share a dataset with my team?

To share a dataset with your team:

1. **Create or join a group**: Ask your administrator to create a group for your team, or create one if you have admin privileges
2. **Set dataset visibility to "Group"**: When creating or editing a dataset, select "Group" as the visibility level
3. **Select your team's group**: Choose the group(s) that should have access to the dataset
4. **Assign appropriate permissions**: Group members can be viewers (read-only) or editors (can modify)

The same process applies to annotation projects.

### What's the difference between groups and visibility?

- **Groups** are collections of users organized by your administrator (e.g., "Research Team", "Annotators")
- **Visibility** determines who can access a specific dataset or project using those groups

For example, you might have a "Bat Researchers" group and set a dataset's visibility to "Group" with that group selected, allowing only bat researchers to access it.

### Can I change visibility after creating a dataset?

Yes! You can update the visibility settings of any dataset or annotation project you own at any time:

1. Navigate to the dataset or project detail page
2. Click the edit/settings button
3. Update the visibility settings
4. Save your changes

Note that changing from "Public" or "Group" to "Private" will immediately restrict access for other users.

## Import and Export

### What is the AOEF format?

The AOEF format is a custom data format designed for integration with Whombat data.
It is outlined in the `soundevent` package, and for a more in-depth understanding, we suggest checking out their [documentation](https://mbsantiago.github.io/soundevent/).
In simple terms, it's a [JSON](https://www.json.org)-based format, drawing heavy inspiration from the [COCO dataset](https://cocodataset.org/#format-data) format.

\*[AOEF]: Acoustic Object Exchange Format
