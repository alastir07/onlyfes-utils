#!/usr/bin/env ruby

require 'fileutils'
require 'set'

class ChatMerger
  def initialize(base_dir = 'C:/Users/danny/.runelite/chatlogs', output_file = 'mega_clan_log.txt')
    @base_dir = base_dir
    @output_file = output_file
  end

  def merge_logs
    puts "Scanning for chat logs in #{@base_dir}/*/clan/*.log"
    log_files = Dir.glob(File.join(@base_dir, '*', 'clan', '*.log'))

    if log_files.empty?
      puts "No .log files found."
      return
    end

    puts "Found #{log_files.length} log file(s)."
    
    # Group logs by date based on their filename (e.g., chatlog_YYYY-MM-DD.log)
    logs_by_date = Hash.new { |h, k| h[k] = [] }
    
    log_files.each do |file_path|
      filename = File.basename(file_path)
      if filename =~ /_?(\d{4}-\d{2}-\d{2})\.log$/
        logs_by_date[$1] << file_path
      else
        # Use last modified date for logs without a date in the filename
        mtime = File.mtime(file_path)
        date_str = mtime.strftime('%Y-%m-%d')
        logs_by_date[date_str] << file_path
      end
    end

    puts "Grouped into #{logs_by_date.keys.length} distinct date(s)."

    total_unique_lines = 0

    File.open(@output_file, 'w', encoding: 'UTF-8') do |output|
      output.puts "================================ MEGA CLAN LOG ================================"
      output.puts "Generated: #{Time.now}"
      
      # Process dates chronologically
      logs_by_date.keys.sort.each do |date|
        date_files = logs_by_date[date]
        unique_messages = Set.new
        parsed_lines = []

        date_files.each do |file_path|
          begin
            content = File.read(file_path, mode: 'rb')
            content = content.force_encoding('UTF-8').scrub('?')
          rescue => encoding_error
            content = File.read(file_path, encoding: 'ISO-8859-1').encode('UTF-8', invalid: :replace, undef: :replace, replace: '?')
          end

          content.each_line do |line|
            line = line.strip
            next if line.empty?

            # Clean the line: replace literal '?', remove <img=\d+> tags for consistency/deduplication
            clean_line = line.gsub('?', ' ')
            clean_line = clean_line.gsub(/<img=\d+>\s*/, '')
            clean_line = clean_line.squeeze(' ') # Replace multiple spaces with a single space

            # Deduplicate based on the clean line
            unless unique_messages.include?(clean_line)
              unique_messages.add(clean_line)
              
              # Try to extract the timestamp (HH:MM:SS) for sorting within the date
              if clean_line =~ /^(\d{2}:\d{2}:\d{2})\s*(.+)$/
                time = $1
                msg = $2
                parsed_lines << { time: time, clean: clean_line }
              else
                parsed_lines << { time: "00:00:00", clean: clean_line }
              end
            end
          end
        end

        # Sort the lines for this date chronologically by time
        parsed_lines.sort_by! { |p| p[:time] }

        total_unique_lines += parsed_lines.length

        output.puts "\n" + "=" * 20 + " Date: #{date} " + "=" * 20
        
        parsed_lines.each do |p|
          # Output format: [YYYY-MM-DD] HH:MM:SS Message
          output.puts "[#{date}] #{p[:clean]}"
        end
        
        puts "Merged #{date}: #{parsed_lines.length} unique messages from #{date_files.length} file(s)."
      end
    end

    puts "=" * 50
    puts "Merge complete!"
    puts "Total unique messages: #{total_unique_lines}"
    puts "Output written to: #{@output_file}"
  end
end

if __FILE__ == $0
  merger = ChatMerger.new
  merger.merge_logs
end
