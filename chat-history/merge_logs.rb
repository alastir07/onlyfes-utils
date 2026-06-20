#!/usr/bin/env ruby

require 'fileutils'

STDOUT.sync = true

CHAT_LOGS_DIRS = Dir.glob('C:/Users/danny/.runelite/chatlogs/*/clan')

output_file = File.expand_path('mega_clan_log.txt', __dir__)

puts "Starting log merging..."
puts "Directories: #{CHAT_LOGS_DIRS.join(', ')}"

# Group log files by date
date_files = Hash.new { |h, k| h[k] = [] }

CHAT_LOGS_DIRS.each do |dir|
  unless Dir.exist?(dir)
    puts "Warning: Directory #{dir} does not exist. Skipping."
    next
  end

  Dir.glob(File.join(dir, "*.log")).each do |file_path|
    filename = File.basename(file_path)
    if match = filename.match(/(\d{4}-\d{2}-\d{2})/)
      date_str = match[1]
      date_files[date_str] << file_path
    end
  end
end

if date_files.empty?
  puts "No log files with dates found to merge."
  exit 1
end

puts "Found logs for #{date_files.keys.length} unique dates."
puts "Sorting and merging..."

# Open output file
File.open(output_file, 'w') do |out|
  # Sort dates chronologically
  date_files.keys.sort.each do |date_str|
    files = date_files[date_str]
    date_lines = []

    files.each do |file_path|
      begin
        content = File.read(file_path, mode: 'rb')
        content = content.force_encoding('UTF-8').scrub('?')
      rescue
        content = File.read(file_path, encoding: 'ISO-8859-1').encode('UTF-8', invalid: :replace, undef: :replace, replace: '?') rescue nil
      end

      next if content.nil?

      content.each_line do |line|
        line = line.strip
        next if line.empty?

        # Extract timestamp
        if match = line.match(/^(\d{2}:\d{2}:\d{2})/)
          timestamp = match[1]
          date_lines << { timestamp: timestamp, line: line }
        else
          # Fallback if line doesn't start with timestamp (e.g. wrapped lines, but rare)
          date_lines << { timestamp: "00:00:00", line: line }
        end
      end
    end

    # Sort lines by timestamp
    date_lines.sort_by! { |item| item[:timestamp] }

    # Write to output file with date prefix
    date_lines.each do |item|
      # We clean up any question marks or weird characters in the final log line
      cleaned_line = item[:line].gsub(/[\u00A0\u200B\s\?]+/, ' ')
      out.puts "[#{date_str}] #{cleaned_line}"
    end
  end
end

puts "Success! Merged log written to: #{output_file}"
puts "File size: #{(File.size(output_file) / 1024.0 / 1024.0).round(2)} MB"
