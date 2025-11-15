#!/usr/bin/env ruby

require 'json'
require 'fileutils'

class DiscordArchiver
  # Configuration - modify these values as needed
  DISCORD_CLI_PATH = './DiscordChatExporter.Cli.win-x64/DiscordChatExporter.Cli.exe'
  
  # Categories to archive - modify this array to specify which categories you want to export
  ARCHIVE_CATEGORY_NAMES = [
    'E-ARCHIVES',
    'PVM-ARCHIVES',
    'STAFF-ARCHIVES-OLD',
    'MOD-ARCHIVES'
    # Add more category names here as needed
  ]

  
  def initialize(token, server_id, output_dir = nil)
    @token = token
    @server_id = server_id
    # Set default output_dir to CURRENT_DATE-Archive if not provided
    if output_dir.nil?
      current_date = Time.now.strftime("%Y-%m-%d")
      @output_dir = "#{current_date}-Archive"
    else
      @output_dir = output_dir
    end
    @cli_path = DISCORD_CLI_PATH

    # Create output directory if it doesn't exist
    FileUtils.mkdir_p(@output_dir) unless Dir.exist?(@output_dir)

    validate_cli_exists
  end
  
  def run
    puts "Starting Discord archiver..."
    start_time = Time.now
    puts "Server ID: #{@server_id}"
    puts "Output directory: #{@output_dir}"
    puts "Categories to archive: #{ARCHIVE_CATEGORY_NAMES.join(', ')}"
    puts "-" * 50
    
    # Step 1: Get all channels from the server
    puts "Fetching all channels from server..."
    all_channels = get_all_channels
    
    if all_channels.empty?
      puts "No channels found or error occurred."
      return
    end
    
    puts "Found #{all_channels.length} total channels"
    
    # Step 2: Filter channels by specified categories
    puts "Filtering channels by categories..."
    filtered_channels = filter_channels_by_category(all_channels)
    
    if filtered_channels.empty?
      puts "No channels found in specified categories: #{ARCHIVE_CATEGORY_NAMES.join(', ')}"
      return
    end
    
    puts "Found #{filtered_channels.length} channels to export:"
    filtered_channels.each do |channel|
      puts "  - #{channel[:category]} / #{channel[:name]} (ID: #{channel[:id]})"
    end
    
    # Step 3: Export each filtered channel
    puts "\nStarting exports..."
    export_channels(filtered_channels)
    
    puts "\nArchiving complete!"
    end_time = Time.now
    puts "Time to export: #{end_time - start_time} seconds"
  end
  
  private
  
  def validate_cli_exists
    unless File.exist?(@cli_path)
      puts "Error: Discord CLI not found at #{@cli_path}"
      puts "Please ensure the DiscordChatExporter CLI is extracted and the path is correct."
      exit 1
    end
  end
  
  def get_all_channels
    command = "\"#{@cli_path}\" channels -t \"#{@token}\" -g #{@server_id}"
    
    puts "Running: #{command.gsub(@token, '[TOKEN_HIDDEN]')}"
    
    output = `#{command} 2>&1`
    exit_status = $?.exitstatus
    
    if exit_status != 0
      puts "Error getting channels (exit code: #{exit_status}):"
      puts output
      return []
    end
    
    # Force encoding to UTF-8 and handle invalid bytes
    output = output.force_encoding('UTF-8')
    unless output.valid_encoding?
      output = output.encode('UTF-8', 'UTF-8', invalid: :replace, undef: :replace, replace: '?')
    end
    
    parse_channels_output(output)
  end
  
  def parse_channels_output(output)
    channels = []
    
    output.each_line do |line|
      line = line.strip
      next if line.empty?
      
      # Skip header lines and separators
      next if line.match(/^(Channel|ID|\||-)/)
      
            # Parse channel line format: 
      # Format 1: CHANNEL_ID | CHANNEL_NAME (no category)
      # Format 2: CHANNEL_ID | CATEGORY / CHANNEL_NAME
      if match = line.match(/^(\d+)\s*\|\s*(.+)$/)
        id = match[1]
        rest = match[2].strip
        
        # Check if there's a category separator " / "
        if rest.include?(' / ')
          parts = rest.split(' / ', 2)
          category = parts[0].strip
          name = parts[1].strip
        else
          # No category, just the channel name
          category = 'No Category'
          name = rest
        end

        channels << {
          id: id,
          category: category.empty? ? 'No Category' : category,
          name: name
        }
      end
    end
    
    channels
  end
  
  def filter_channels_by_category(channels)
    # Convert category names to lowercase for case-insensitive substring matching
    target_categories = ARCHIVE_CATEGORY_NAMES.map(&:downcase)
    
    channels.select do |channel|
      category_lower = channel[:category].downcase
      target_categories.any? { |target| category_lower.include?(target) }
    end
  end
  
  def export_channels(channels)
    total = channels.length
    success_count = 0
    
    channels.each_with_index do |channel, index|
      puts "\n[#{index + 1}/#{total}] Exporting: #{channel[:category]} / #{channel[:name]}"
      
      if export_channel(channel)
        success_count += 1
        puts "  ✓ Success"
      else
        puts "  ✗ Failed"
      end
    end
    
    puts "\nExport summary: #{success_count}/#{total} channels exported successfully"
  end
  
  def export_channel(channel)
    # Create output path using template tokens for organization
    # Format: output_dir/Server Name/Category/channel-name.html
    output_path = File.join(@output_dir, "%T", "%C.json")
    
    command = [
      "\"#{@cli_path}\"",
      "export",
      "-t \"#{@token}\"",
      "-c #{channel[:id]}",
      "-o \"#{output_path}\"",
      "-f json",
      "--include-threads All"
    ].join(' ')
    
    puts "  Running export command..."
    channel_start_time = Time.now
    
    output = `#{command} 2>&1`
    exit_status = $?.exitstatus
    
    if exit_status != 0
      puts "  Error (exit code: #{exit_status}):"
      puts "  #{output}"
      return false
    end
    
    channel_end_time = Time.now
    puts "  Time to export #{channel[:name]}: #{channel_end_time - channel_start_time} seconds"
    
    true
  end
end

# Usage example and main execution
if __FILE__ == $0
  if ARGV.length < 2
    puts "Usage: ruby discord_archiver.rb <token> <server_id> [output_dir]"
    puts ""
    puts "Arguments:"
    puts "  token      - Your Discord token"
    puts "  server_id  - The server/guild ID to export from"
    puts "  output_dir - Output directory (optional, defaults to 'CURRENT_DATE-Archive')"
    puts ""
    puts "Example:"
    puts "  ruby discord_archiver.rb \"mfa.your_token_here\" 123456789 \"my_exports\""
    puts ""
    puts "Note: Modify the ARCHIVE_CATEGORY_NAMES array in the script to specify"
    puts "      which categories you want to export."
    exit 1
  end
  
  token = ARGV[0]
  server_id = ARGV[1]
  output_dir = ARGV[2] || nil
  
  archiver = DiscordArchiver.new(token, server_id, output_dir)
  archiver.run
end
