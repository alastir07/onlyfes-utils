# Discord Archiver Ruby Script

This Ruby script automates the Discord CLI export process by:
1. Getting a list of all channels from a specified server
2. Filtering channels to only those in specified categories
3. Exporting each filtered channel

## Setup

1. Ensure you have Ruby installed on your system
2. Make sure the DiscordChatExporter CLI is extracted in the `DiscordChatExporter.Cli.win-x64` folder
3. Get your Discord token (see the main CLI documentation for instructions)
4. Get the Guild ID of the server you want to export from

## Configuration

Edit the `ARCHIVE_CATEGORY_NAMES` array in `discord_archiver.rb` to specify which categories you want to export:

```ruby
ARCHIVE_CATEGORY_NAMES = [
  'General',
  'Text Channels', 
  'Important',
  'Announcements',
  # Add more category names here
]
```

## Usage

```bash
ruby discord_archiver.rb <token> <guild_id> [output_dir]
```

### Arguments:
- `token` - Your Discord token (required)
- `guild_id` - The server/guild ID to export from (required)  
- `output_dir` - Output directory (optional, defaults to 'exports')

### Example:
```bash
ruby discord_archiver.rb "mfa.your_token_here" 123456789012345678 "my_discord_exports"
```

## Output Structure

The script will create organized exports using the following structure:
```
output_dir/
├── Server Name/
│   ├── Category 1/
│   │   ├── channel1.html
│   │   └── channel2.html
│   └── Category 2/
│       ├── channel3.html
│       └── channel4.html
```

## Features

- **Category Filtering**: Only exports channels from specified categories
- **Organized Output**: Uses Discord CLI template tokens to organize exports by server and category
- **Media Downloads**: Downloads and reuses media files (avatars, attachments, etc.)
- **Progress Tracking**: Shows progress and success/failure status for each channel
- **Error Handling**: Provides clear error messages and continues processing other channels if one fails

## Notes

- The script uses the `HtmlDark` format by default
- Media files are downloaded and reused to avoid redundant downloads
- Voice channels are automatically filtered out (only text channels are exported)
- Case-insensitive category matching is used
- The script will create the output directory if it doesn't exist

## Troubleshooting

- Make sure the Discord CLI path is correct in the script
- Verify your token has access to the specified server
- Check that the category names in `ARCHIVE_CATEGORY_NAMES` match exactly (case-insensitive)
- Ensure you have write permissions to the output directory
