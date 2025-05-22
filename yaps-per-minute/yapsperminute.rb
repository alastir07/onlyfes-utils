require 'time'
require 'csv'
require 'optparse'

options = {}
OptionParser.new do |opts|
  opts.banner = "Usage: yapsperminute.rb [options]"

  opts.on("-f", "--file FILE", "File to parse") do |file|
    options[:file] = file

    if !File.exist?(options[:file])
      puts "Error: File does not exist"
      exit
    end
  end

  opts.on("-h", "--help", "Prints this help") do
    puts opts
    exit
  end
end.parse!

def clean_username(username)
  # Replace various special space characters with a regular space
  username.gsub(/[\u00A0\u202F\u2007\u200B]/, ' ')
         .gsub(/\u{FEFF}/, '')  # Remove zero-width no-break space
         .gsub(/[^\x20-\x7E]/, ' ')  # Replace any other non-ASCII characters with space
end

def parse_chat_log(file_path)
  # Initialize hash to store user message counts
  user_messages = Hash.new(0)
  timestamps = []
  last_timestamp = nil
  skip_next_interval = false
  removed_intervals = []
  
  if file_path.nil? ||!File.exist?(file_path)
    puts "Error: File does not exist or is not provided"
    exit
  end

  # Read the log file line by line with proper encoding handling
  File.open(file_path, 'r:UTF-8:UTF-8', invalid: :replace, undef: :replace) do |file|
    file.each_line do |line|
      # Force encoding and clean the line
      line = line.encode('UTF-8', invalid: :replace, undef: :replace)
      
      # First try to match regular chat messages
      if match = line.match(/(\d{2}:\d{2}:\d{2})\s+<img=\d+>([^:]+):/)
        timestamp = match[1]
        username = clean_username(match[2].strip)
        message = line.split(':', 2)[1].strip
        
        # Store timestamp
        timestamps << timestamp
        
        last_timestamp = timestamp
        user_messages[username] += 1
      # Then try to match system messages (which don't have the img tag)
      elsif match = line.match(/(\d{2}:\d{2}:\d{2})\s+(.*)/)
        timestamp = match[1]
        message = match[2].strip
        
        # Check for the special message
        if message.include?("To talk in your clan's channel, start each line of chat with // or /c")
          skip_next_interval = true
          puts "Skipping interval from #{last_timestamp} to #{timestamp}"
          if last_timestamp
            removed_intervals << [last_timestamp, timestamp]
          end
        elsif skip_next_interval && last_timestamp
          # Skip the interval between the special message and the previous message
          timestamps.pop # Remove the special message timestamp
          timestamps.pop # Remove the previous message timestamp
          skip_next_interval = false
        end
        
        last_timestamp = timestamp
      end
    end
  end

  # Sort users by message count in descending order
  sorted_users = user_messages.sort_by { |username, count| -count }
  
  # Calculate total duration and messages per minute
  total_messages = sorted_users.sum { |_, c| c }
  total_duration_minutes = 0
  removed_duration_minutes = 0
  
  if timestamps.length >= 2
    first_time = Time.parse(timestamps.first)
    last_time = Time.parse(timestamps.last)
    total_duration = last_time - first_time
    total_duration_minutes = total_duration / 60.0
    
    # Calculate removed intervals
    removed_intervals.each do |start_time, end_time|
      start = Time.parse(start_time)
      finish = Time.parse(end_time)
      removed_duration_minutes += (finish - start) / 60.0
    end
    
    hours = (total_duration / 3600).floor
    minutes = ((total_duration % 3600) / 60).floor
    seconds = (total_duration % 60).floor
    
    removed_hours = (removed_duration_minutes / 60).floor
    removed_minutes = (removed_duration_minutes % 60).floor
    removed_seconds = ((removed_duration_minutes * 60) % 60).floor
  end
  
  # Prepare data for CSV
  csv_data = sorted_users.map do |username, count|
    percentage = (count.to_f / total_messages * 100).round(1)
    messages_per_minute = (count.to_f / (total_duration_minutes - removed_duration_minutes)).round(2)
    [username, count, percentage, messages_per_minute]
  end
  
  # Write to CSV
  CSV.open("chat_stats.csv", "w") do |csv|
    csv << ["Username", "Messages", "Percentage", "Yaps Per Minute"]
    csv_data.each { |row| csv << row }
  end
  
  # Print results (top 10 only)
  puts "Message counts by user (Top 10):"
  puts "-" * 50
  puts "Username".ljust(20) + "Messages".ljust(10) + "Percentage".ljust(12) + "Yaps Per Minute"
  puts "-" * 50
  
  csv_data.first(10).each do |username, count, percentage, messages_per_minute|
    puts "#{username.ljust(20)}#{count.to_s.ljust(10)}#{percentage.to_s.ljust(12)}#{messages_per_minute}"
  end
  
  puts "\nTime period:"
  puts "-" * 30
  if timestamps.length >= 2
    puts "From: #{timestamps.first}"
    puts "To: #{timestamps.last}"
    puts "Duration: #{hours}h #{minutes}m #{seconds}s"
    if removed_duration_minutes > 0
      puts "Removed intervals: #{removed_hours}h #{removed_minutes}m #{removed_seconds}s"
      effective_duration = total_duration_minutes - removed_duration_minutes
      effective_hours = (effective_duration / 60).floor
      effective_minutes = (effective_duration % 60).floor
      effective_seconds = ((effective_duration * 60) % 60).floor
      puts "Effective duration: #{effective_hours}h #{effective_minutes}m #{effective_seconds}s"
    end
    puts "Total messages: #{total_messages}"
    puts "Average messages per minute: #{(total_messages.to_f / (total_duration_minutes - removed_duration_minutes)).round(2)}"
  else
    puts "Not enough messages to calculate time period"
  end
  
  puts "\nFull results have been saved to chat_stats.csv"
end

# Example usage:
parse_chat_log(options[:file])
