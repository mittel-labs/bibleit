gen() {
    local target="../src/bibleit/translations/$1"

    if [ ! -f "$target" ];
    then
        echo "Error: translation '${target}' not found"
        exit 1
    fi

    local chapters_file="diff.$1.chapters"
    local chapters_count_file="diff.$1.chapters.count"

    echo "> $target"

    echo "Generating chapters.."
    awk -F: '{print $1}' $target | uniq > $chapters_file

    echo "Generating counting.."
    cat $chapters_file | xargs -I% bash -c 'echo -n "% $ "; grep -c "^%:" '"$target"'' > $chapters_count_file

    echo "done"
}


for arg in "$@"
do
    gen $arg &
done
