# !/bin/bash
set -eo pipefail
echo "pwd: $(pwd)"

function build_diopi_lib() {
    cd third_party/DIOPI/impl
    sh scripts/build_impl.sh clean
    sh scripts/build_impl.sh ascend || exit -1
    cd -
}

function config_dipu_ascend_cmake() {
    mkdir -p build && cd ./build && rm -rf ./*
    cmake ../  -DCMAKE_BUILD_TYPE=Debug \
        -DDEVICE=ascend
    cd ../
}

function config_all_ascend_cmake() {
    mkdir -p build && cd ./build && rm -rf ./*
    cmake ../  -DCMAKE_BUILD_TYPE=Debug \
        -DDEVICE=ascend \
        -DWITH_DIOPI=INTERNAL
    cd ../
}

function build_dipu_lib() {
    echo "building dipu_lib:$(pwd)"
    echo  "DIOPI_ROOT:${DIOPI_ROOT}"
    config_dipu_ascend_cmake 2>&1 | tee ./build1.log
    cd build && make -j8  2>&1 | tee ./build1.log &&  cd ..
}

function build_all() {
    echo "building dipu_lib:$(pwd)"
    echo  "DIOPI_ROOT:${DIOPI_ROOT}"
    config_all_ascend_cmake 2>&1 | tee ./build1.log
    cd build && make -j8  2>&1 | tee ./build1.log &&  cd ..
}

case $1 in
    build_dipu)
        (
            build_all
        ) \
        || exit -1;;
    *)
        echo -e "[ERROR] Incorrect option:" $1;
esac
exit 0
